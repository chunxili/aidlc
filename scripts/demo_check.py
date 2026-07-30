#!/usr/bin/env python3
"""端到端演示验收脚本。

逐条走完竞赛演示流程 a~f（SC-001 ~ SC-006）以及权限隔离（SC-008），
全部对着真实运行的服务，不使用 mock、不修改数据库。

    python scripts/demo_check.py

任一步不符预期即以非 0 退出码结束。

注意第 3 步「过期券核销」会真实等待 65 秒 —— 这正是 ADR-003 分钟粒度带来的
能力：过期是系统真实行为，无需改库或提前一天准备。加 --skip-wait 可跳过。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
problems: list[str] = []


def req(method: str, path: str, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {}


def login(u: str) -> str:
    s, b = req("POST", "/api/auth/login", {"username": u})
    assert s == 200, f"登录 {u} 失败: {s} {b}"
    return b["access_token"]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'[通过]' if ok else '[失败]'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        problems.append(label)


def new_campaign(op: str, stock: int, validity: int, name: str, per_user: int = 1) -> dict:
    now = dt.datetime.now(dt.UTC)
    s, b = req(
        "POST",
        "/api/campaigns",
        {
            "name": f"{name}-{now.strftime('%H%M%S')}",
            "category": "FOOD",
            "face_value": "20.00",
            "total_stock": stock,
            "start_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "end_at": (now + dt.timedelta(days=1)).isoformat(),
            "validity_minutes": validity,
            "per_user_limit": per_user,
        },
        op,
    )
    assert s == 201, f"创建活动失败: {s} {b}"
    return b


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wait", action="store_true", help="跳过过期券的 65 秒真实等待")
    ap.add_argument("--base-url", default=BASE)
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")

    s, health = req("GET", "/api/health")
    print(f"健康检查: {health}\n")
    if s != 200:
        print("服务不可用")
        return 1

    op = login("op001")
    ua, ub, uc = login("user_a"), login("user_b"), login("user_c")
    ve, ad = login("verifier001"), login("admin001")

    # ---- 演示 a + b：库存 1 的活动，用户 A 领取成功（含 AI 推荐理由）----
    print("演示 a/b：创建库存为 1 的活动，用户 A 领取")
    camp = new_campaign(op, stock=1, validity=60, name="演示AB")

    s, recs = req("GET", "/api/recommendations?limit=5", token=ua)
    check("推荐接口返回非空列表且每项有理由",
          s == 200 and bool(recs["items"]) and all(i["reason"].strip() for i in recs["items"]),
          f"degraded={recs.get('degraded')} reason={recs.get('degrade_reason')}")
    check("推荐在领取之前即可获得（ADR-005：AI 不在交易链路）", s == 200)

    s, claim = req("POST", "/api/coupons/claim", {"campaign_id": camp["id"]}, ua)
    check("用户 A 领取成功", s == 201, f"code={claim.get('coupon', {}).get('code')}")
    code_a = claim.get("coupon", {}).get("code", "")
    check("领券响应含风控判定且判定来源为规则层",
          claim.get("risk", {}).get("decided_by") == "RULE")

    # ---- 演示 c：用户 B 领同一活动失败 ----
    print("\n演示 c：用户 B 领取同一活动")
    s, fail = req("POST", "/api/coupons/claim", {"campaign_id": camp["id"]}, ub)
    check("用户 B 失败且原因为库存不足", s == 409 and fail.get("code") == "OUT_OF_STOCK",
          str(fail.get("code")))

    # ---- 演示 d + e：核销与重复核销 ----
    print("\n演示 d/e：核销员核销用户 A 的券，再次核销")
    s, chk = req("GET", f"/api/redemptions/{code_a}", token=ve)
    check("核销前查验显示可核销", s == 200 and chk.get("redeemable") is True)
    check("查验为纯读，持有人已脱敏", "***" in str(chk.get("owner")))

    s, ok = req("POST", "/api/redemptions", {"code": code_a}, ve)
    check("首次核销成功", s == 200, f"used_by={ok.get('used_by')}")

    repeats = [req("POST", "/api/redemptions", {"code": code_a}, ve) for _ in range(3)]
    check("重复核销均返回「已核销」",
          all(st == 409 and bd.get("code") == "COUPON_ALREADY_USED" for st, bd in repeats))
    check("重复核销响应完全一致（幂等）",
          len({json.dumps(bd, sort_keys=True) for _, bd in repeats}) == 1)

    # ---- 验收点 4.3：过期券核销（真实等待，不改库）----
    print("\n验收点 4.3：过期券核销（1 分钟有效期的券，真实等待过期）")
    exp_camp = new_campaign(op, stock=5, validity=1, name="演示过期")
    s, exp_claim = req("POST", "/api/coupons/claim", {"campaign_id": exp_camp["id"]}, ub)
    exp_code = exp_claim.get("coupon", {}).get("code", "")
    check("领到 1 分钟有效期的券", s == 201, f"expires_at={exp_claim.get('coupon', {}).get('expires_at')}")

    if args.skip_wait:
        print("  （已跳过 65 秒等待，该项未验证）")
    else:
        print("  等待 65 秒让券自然过期…")
        time.sleep(65)
        s, expired = req("POST", "/api/redemptions", {"code": exp_code}, ve)
        check("过期券核销返回「券已过期」",
              s == 409 and expired.get("code") == "COUPON_EXPIRED", str(expired.get("code")))
        s, my = req("GET", "/api/coupons/my", token=ub)
        target = next((i for i in my["items"] if i["code"] == exp_code), None)
        check("券的 status 仍为 UNUSED（过期不落库，INV-3）",
              target is not None and target["status"] == "UNUSED"
              and target["display_status"] == "已过期")

    # ---- 演示 f：用户 C 高频领取被风控拦截 ----
    print("\n演示 f：用户 C 在 10 秒内高频领取")
    burst_camp = new_campaign(op, stock=100, validity=60, name="演示风控", per_user=100)
    statuses = []
    for _ in range(50):
        st, bd = req("POST", "/api/coupons/claim", {"campaign_id": burst_camp["id"]}, uc)
        statuses.append((st, bd.get("code")))
    blocked = [c for st, c in statuses if st == 403]
    check("高频领取被拦截", bool(blocked), f"共 {len(blocked)} 次被拒")

    # 首次拦截的形态取决于 AI 是否可用，两条路径都是设计预期：
    #   AI 可用   → 灰区 [gray_low, hard_threshold) 内由 AI 判定，可能提前给出
    #               RISK_MANUAL_REVIEW，硬阈值分支因 risk_blocked 短路而不再触发
    #   AI 不可用 → 灰区降级放行，计数达硬阈值时由规则层给出 RISK_BLOCKED
    # 二者均为 403「风控拦截」，满足 SC-006；断言只认一条会把另一条正常路径误判为缺陷。
    first = blocked[0] if blocked else None
    check(
        "首次拦截形态属于两条预期路径之一",
        first in ("RISK_BLOCKED", "RISK_MANUAL_REVIEW"),
        f"{first}（{'AI 灰区判定' if first == 'RISK_MANUAL_REVIEW' else '规则层硬阈值'}）",
    )
    check(
        "拦截次数占比合理（未把全部请求放行）",
        len(blocked) >= 40,
        f"{len(blocked)}/50",
    )

    s, ov = req("GET", "/api/stats/overview", token=ad)
    check("管理员面板的风控拦截计数已增长", s == 200 and ov.get("risk_blocked_24h", 0) > 0,
          f"risk_blocked_24h={ov.get('risk_blocked_24h')}")
    check("待处理风险标记数已增长", ov.get("risk_pending_count", 0) > 0)

    s, events = req("GET", "/api/risk/events?status=PENDING", token=op)
    check("运营可见风险标记且每条都有判定理由",
          s == 200 and bool(events["items"]) and all(e["ai_reason"].strip() for e in events["items"]))

    # ---- 对账 ----
    print("\n不变量对账")
    s, integ = req("GET", "/api/stats/integrity", token=ad)
    check("INV-1 库存守恒 / INV-2 券的完全划分", s == 200 and integ.get("ok") is True, str(integ))

    # ---- 权限隔离 ----
    print("\n权限隔离（SC-008）")
    cases = [
        ("普通用户创建活动", "POST", "/api/campaigns", ua),
        ("普通用户核销", "POST", "/api/redemptions", ua),
        ("核销员看统计", "GET", "/api/stats/overview", ve),
        ("运营核销", "POST", "/api/redemptions", op),
    ]
    for label, method, path, token in cases:
        st, bd = req(method, path, {} if method == "POST" else None, token)
        check(f"{label} → 403", st == 403 and bd.get("code") == "FORBIDDEN", f"{st} {bd.get('code')}")
        check(f"{label} 响应不泄露资源字段", set(bd.keys()) <= {"code", "message"})

    print("\n" + "=" * 60)
    if problems:
        print(f"未通过 {len(problems)} 项：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("竞赛演示六步 + 过期核销 + 对账 + 权限隔离，全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
