#!/usr/bin/env python3
"""并发验收脚本（FR-070）。

作用：一条命令当场证明库存不会超发，并作为回归测试。

    python scripts/concurrency_check.py --stock 100
    python scripts/concurrency_check.py --stock 1        # 对应竞赛演示步骤 c

为什么必须有这个脚本：验收点"库存 N，N+1 个并发请求只有 N 个成功"**无法靠点鼠标
验证**。这是唯一能证明不超发的手段，也是演示时最有力的一击。

关键约束：**必须使用 N+1 个不同用户**。同一用户会被风控按 user_id 拦截，
导致"成功数远小于 N"而被误判为库存扣减缺陷（D-08）。

不变量不成立时以非 0 退出码结束，便于接入 CI。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

DEFAULT_BASE = "http://127.0.0.1:8000"


def _request(base: str, method: str, path: str, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"code": "NON_JSON", "raw": raw[:200].decode(errors="replace")}
    except Exception as exc:
        return 0, {"code": "TRANSPORT_ERROR", "message": f"{type(exc).__name__}: {exc}"}


def login(base: str, username: str, attempts: int = 3) -> str:
    """登录并取 token。

    带重试：登录阶段是**准备工作**，不是被测对象。urllib 在 Windows 上大量并发
    时偶发 socket 超时，若不重试会让准备阶段的偶发故障伪装成被测缺陷。
    """
    last: tuple[int, dict] = (0, {})
    for _ in range(attempts):
        status, body = _request(base, "POST", "/api/auth/login", {"username": username})
        if status == 200:
            return body["access_token"]
        last = (status, body)
    raise SystemExit(f"登录失败 {username}: {last[0]} {last[1]}")


def create_campaign(base: str, token: str, stock: int) -> dict:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "name": f"并发验收-库存{stock}-{now.strftime('%H%M%S')}",
        "category": "FOOD",
        "face_value": "10.00",
        "total_stock": stock,
        "start_at": (now - dt.timedelta(minutes=1)).isoformat(),
        "end_at": (now + dt.timedelta(days=1)).isoformat(),
        "validity_minutes": 60,
        "per_user_limit": 1,
    }
    status, body = _request(base, "POST", "/api/campaigns", payload, token)
    if status != 201:
        raise SystemExit(f"创建活动失败: {status} {body}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="库存不超发并发验收（FR-070）")
    parser.add_argument("--stock", type=int, default=100, help="活动库存 N，并发数为 N+1")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--operator", default="op001")
    parser.add_argument("--admin", default="admin001")
    args = parser.parse_args()

    base, stock = args.base_url.rstrip("/"), args.stock
    concurrency = stock + 1

    print(f"目标: {base}")
    status, health = _request(base, "GET", "/api/health")
    if status != 200:
        raise SystemExit(f"服务不可用: {status} {health}")
    print(f"健康检查: {health}")

    op_token = login(base, args.operator)
    campaign = create_campaign(base, op_token, stock)
    print(f"活动 id={campaign['id']} 库存={stock}，并发请求数={concurrency}")

    # N+1 个**不同**用户：同一用户会被风控拦截（D-08）
    usernames = [f"user{i:03d}" for i in range(1, concurrency + 1)]
    # 登录阶段刻意用低并发：它只是准备工作，把并发留给真正被测的领取阶段。
    print(f"登录 {len(usernames)} 个不同用户…")
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda u: login(base, u), usernames))

    def claim(token: str):
        return _request(
            base, "POST", "/api/coupons/claim", {"campaign_id": campaign["id"]}, token
        )

    print(f"发起 {concurrency} 个并发领取请求…")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(claim, tokens))

    success = sum(1 for s, _ in results if s == 201)
    failures = Counter(b.get("code", f"HTTP_{s}") for s, b in results if s != 201)

    print("\n---- 结果 ----")
    print(f"成功: {success}")
    print(f"失败: {sum(failures.values())}  明细: {dict(failures)}")

    # 用管理员视角核对不变量（INV-1、INV-2）
    admin_token = login(base, args.admin)
    _, stats = _request(base, "GET", f"/api/stats/campaigns/{campaign['id']}", token=admin_token)
    _, integrity = _request(base, "GET", "/api/stats/integrity", token=admin_token)
    print(
        f"服务端统计: claimed_count={stats.get('claimed_count')}"
        f" remaining={stats.get('remaining_stock')}"
        f" 券数(已核销+可用+已过期)="
        f"{stats.get('used_count', 0) + stats.get('active_count', 0) + stats.get('expired_count', 0)}"
    )
    print(f"对账端点: {integrity}")

    print("\n---- 断言 ----")
    problems: list[str] = []

    if success != stock:
        problems.append(f"成功数 {success} != 库存 {stock}")
    else:
        print(f"[通过] 恰好 {stock} 个请求成功")

    if sum(failures.values()) != 1:
        problems.append(f"失败数 {sum(failures.values())} != 1")
    elif set(failures) != {"OUT_OF_STOCK"}:
        problems.append(f"失败原因不是库存不足: {dict(failures)}")
    else:
        print("[通过] 唯一的失败原因是库存不足")

    if failures.get("RISK_BLOCKED") or failures.get("RISK_MANUAL_REVIEW"):
        problems.append("出现风控拦截，说明未使用不同用户（见脚本头部说明）")

    if stats.get("claimed_count") != stock:
        problems.append(f"claimed_count={stats.get('claimed_count')} != {stock}")
    else:
        print(f"[通过] claimed_count = {stock}")

    coupon_total = (
        stats.get("used_count", 0) + stats.get("active_count", 0) + stats.get("expired_count", 0)
    )
    if coupon_total != stock:
        problems.append(f"实际券数 {coupon_total} != {stock}（INV-2 不成立）")
    else:
        print(f"[通过] INV-2 券的完全划分成立，实际券数 = {stock}")

    if not integrity.get("ok"):
        problems.append(f"对账端点报告不一致: {integrity}")
    else:
        print("[通过] INV-1 与 INV-2 对账端点均为 ok")

    if problems:
        print("\n不变量被破坏:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"\n全部通过：库存 {stock}，{concurrency} 个并发请求，成功 {stock}，失败 1（库存不足）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
