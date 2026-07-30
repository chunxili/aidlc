#!/usr/bin/env python3
"""产品化改造端到端验收（CR-001）。

对着真实运行的服务走完新增的四条业务流程，不使用 mock、不修改数据库：

1. 会员自助注册 → 即时可用
2. 核销员注册（选门店）→ 待审核 → 管理员通过 → 可核销
3. 运营注册 → 被驳回 → 看到原因 → 重新提交
4. 满减券与折扣券的门槛校验与优惠计算

    python scripts/product_check.py

任一步不符预期即以非 0 退出码结束。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

BASE = "http://127.0.0.1:8000"
SEED_PASSWORD = "Coupon@2026"
TEST_PASSWORD = "Product@2026"
problems: list[str] = []


def req(method: str, path: str, body=None, token=None):
    data = json.dumps(body, default=str).encode() if body is not None else None
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


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'[通过]' if ok else '[失败]'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        problems.append(label)


def login(username: str, password: str):
    return req("POST", "/api/auth/login", {"username": username, "password": password})


def uniq(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def new_campaign(op: str, **kw) -> dict:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "name": kw.pop("name", "验收活动"),
        "category": "FOOD",
        "coupon_type": "CASH",
        "face_value": "20.00",
        "min_order_amount": "0",
        "total_stock": 10,
        "start_at": (now - dt.timedelta(minutes=1)).isoformat(),
        "end_at": (now + dt.timedelta(days=1)).isoformat(),
        "validity_minutes": 120,
        "per_user_limit": 1,
    }
    payload.update(kw)
    s, b = req("POST", "/api/campaigns", payload, op)
    assert s == 201, f"创建活动失败: {s} {b}"
    return b


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=BASE)
    BASE = ap.parse_args().base_url.rstrip("/")

    s, health = req("GET", "/api/health")
    print(f"健康检查: {health}\n")
    if s != 200:
        print("服务不可用")
        return 1

    _, admin_body = login("admin001", SEED_PASSWORD)
    admin = admin_body["access_token"]
    _, op_body = login("op001", SEED_PASSWORD)
    op = op_body["access_token"]

    # ---------- 门店主数据 ----------
    print("门店主数据")
    s, stores = req("GET", "/api/stores")
    districts = {x["district"] for x in stores}
    check("门店列表可公开访问", s == 200, f"{len(stores)} 家门店")
    check("覆盖广州多个行政区", len(districts) >= 8, "、".join(sorted(districts)[:6]) + " …")
    check("地址均为广州", all(x["address"].startswith("广州市") for x in stores))

    # ---------- 流程 1：会员注册即时可用 ----------
    print("\n流程 1：会员自助注册")
    member = uniq("m_")
    s, body = req(
        "POST",
        "/api/auth/register",
        {
            "username": member,
            "password": TEST_PASSWORD,
            "display_name": "验收会员",
            "role": "USER",
            "phone": "13712345678",
        },
    )
    check("注册成功", s == 201, str(body.get("user", {}).get("status")))
    check("无需审核", body.get("needs_approval") is False)
    s, login_body = login(member, TEST_PASSWORD)
    check("可立即登录", s == 200)
    member_token = login_body.get("access_token", "")
    s, _ = req("GET", "/api/coupons/my", token=member_token)
    check("可立即使用业务接口", s == 200)
    s, _ = login(member, "wrong-password")
    check("错误口令被拒绝", s == 401)

    # ---------- 流程 2：核销员注册 → 审核 → 可核销 ----------
    print("\n流程 2：核销员注册需选门店并经审核")
    verifier = uniq("v_")
    s, body = req(
        "POST",
        "/api/auth/register",
        {
            "username": verifier,
            "password": TEST_PASSWORD,
            "display_name": "验收核销员",
            "role": "VERIFIER",
        },
    )
    check("不选门店被拒绝", s == 400, str(body.get("message"))[:40])

    store = stores[0]
    s, body = req(
        "POST",
        "/api/auth/register",
        {
            "username": verifier,
            "password": TEST_PASSWORD,
            "display_name": "验收核销员",
            "role": "VERIFIER",
            "store_id": store["id"],
            "phone": "13712345679",
        },
    )
    check("选门店后注册成功", s == 201)
    check("状态为待审核", body.get("needs_approval") is True)

    s, vlogin = login(verifier, TEST_PASSWORD)
    check("待审核账号可登录看进度", s == 200)
    vtoken = vlogin.get("access_token", "")
    s, me = req("GET", "/api/auth/me", token=vtoken)
    check("可查询自己的申请状态", s == 200 and me.get("status") == "PENDING")
    s, blocked = req("GET", "/api/redemptions/ABCDEFGHJK", token=vtoken)
    check(
        "待审核账号不得办业务且给出专用错误码",
        s == 403 and blocked.get("code") == "ACCOUNT_PENDING_APPROVAL",
        str(blocked.get("code")),
    )

    s, pending = req("GET", "/api/admin/registrations", token=admin)
    target = next((u for u in pending if u["username"] == verifier), None)
    check("管理员可见待审申请", target is not None)
    check("待审列表显示所选门店", bool(target and target.get("store_name")), str(target and target.get("store_name")))

    s, _ = req(
        "POST", f"/api/admin/registrations/{target['id']}/review", {"approve": True}, admin
    )
    check("管理员通过申请", s == 200)
    s, vlogin2 = login(verifier, TEST_PASSWORD)
    vtoken = vlogin2.get("access_token", "")
    s, after = req("GET", "/api/redemptions/ABCDEFGHJK", token=vtoken)
    check("通过后可访问核销接口", s == 404, f"券不存在而非被拒（{s}）")

    s, roster = req("GET", "/api/admin/verifiers", token=admin)
    check("名册包含新核销员", any(v["username"] == verifier for v in roster))
    check("名册覆盖多个门店", len({v["store_id"] for v in roster}) >= 2)
    s, filtered = req("GET", f"/api/admin/verifiers?district={store['district']}", token=admin)
    check(
        "名册可按行政区筛选",
        bool(filtered) and {v["store_district"] for v in filtered} == {store["district"]},
    )

    # ---------- 流程 3：运营注册被驳回 → 重新提交 ----------
    print("\n流程 3：运营注册被驳回后重新提交")
    operator = uniq("o_")
    req(
        "POST",
        "/api/auth/register",
        {
            "username": operator,
            "password": TEST_PASSWORD,
            "display_name": "验收运营",
            "role": "OPERATOR",
        },
    )
    s, pending = req("GET", "/api/admin/registrations", token=admin)
    target = next(u for u in pending if u["username"] == operator)
    req(
        "POST",
        f"/api/admin/registrations/{target['id']}/review",
        {"approve": False, "reason": "请补充部门证明"},
        admin,
    )
    s, rejected = req("POST", "/api/auth/login", {"username": operator, "password": TEST_PASSWORD})
    check(
        "被驳回账号不可登录且告知原因",
        s == 403 and "请补充部门证明" in str(rejected.get("message")),
        str(rejected.get("code")),
    )
    s, again = req(
        "POST",
        "/api/auth/register",
        {
            "username": operator,
            "password": TEST_PASSWORD,
            "display_name": "验收运营",
            "role": "OPERATOR",
        },
    )
    check("可用同一账号重新提交", s == 201 and again["user"]["status"] == "PENDING")

    # ---------- 流程 4：券型与门槛 ----------
    print("\n流程 4：满减券与折扣券")
    verifier_token = login("verifier001", SEED_PASSWORD)[1]["access_token"]
    member_token = login("user_a", SEED_PASSWORD)[1]["access_token"]

    cash = new_campaign(
        op, name="满 100 减 30", coupon_type="CASH", face_value="30.00", min_order_amount="100.00"
    )
    check("满减券优惠描述由后端生成", "满 100 减 30" in cash["benefit_text"], cash["benefit_text"])

    s, claim = req("POST", "/api/coupons/claim", {"campaign_id": cash["id"]}, member_token)
    code = claim.get("coupon", {}).get("code", "")
    check("领取满减券", s == 201, code)

    s, low = req(
        "POST", "/api/redemptions", {"code": code, "order_amount": "99.99"}, verifier_token
    )
    check(
        "未达门槛被拒绝且提示门槛金额",
        s == 409 and low.get("code") == "ORDER_AMOUNT_BELOW_THRESHOLD",
        str(low.get("message")),
    )

    s, ok = req(
        "POST", "/api/redemptions", {"code": code, "order_amount": "150.00"}, verifier_token
    )
    check("达门槛后核销成功", s == 200)
    check(
        "满减券优惠额等于减免额",
        Decimal(str(ok.get("discount_amount"))) == Decimal("30.00"),
        f"优惠 {ok.get('discount_amount')} 应付 {ok.get('payable_amount')}",
    )
    check("核销结果记录门店", bool(ok.get("store_name")), str(ok.get("store_name")))

    s, repeat = req(
        "POST", "/api/redemptions", {"code": code, "order_amount": "10.00"}, verifier_token
    )
    check(
        "已核销的券即使金额不达标也回「已核销」",
        repeat.get("code") == "COUPON_ALREADY_USED",
        str(repeat.get("code")),
    )

    disc = new_campaign(
        op,
        name="满 200 享 8.5 折",
        coupon_type="DISCOUNT",
        face_value=None,
        discount_percent=85,
        max_discount_amount="50.00",
        min_order_amount="200.00",
    )
    check("折扣券描述含折数与封顶", "8.5 折" in disc["benefit_text"] and "最高减 50" in disc["benefit_text"], disc["benefit_text"])

    member_b = login("user_b", SEED_PASSWORD)[1]["access_token"]
    s, claim2 = req("POST", "/api/coupons/claim", {"campaign_id": disc["id"]}, member_b)
    code2 = claim2.get("coupon", {}).get("code", "")
    s, d1 = req(
        "POST", "/api/redemptions", {"code": code2, "order_amount": "300.00"}, verifier_token
    )
    check(
        "折扣券按比例计算优惠",
        s == 200 and Decimal(str(d1.get("discount_amount"))) == Decimal("45.00"),
        f"300 元 8.5 折应优惠 45，实际 {d1.get('discount_amount')}",
    )

    disc2 = new_campaign(
        op,
        name="封顶验证券",
        coupon_type="DISCOUNT",
        face_value=None,
        discount_percent=85,
        max_discount_amount="50.00",
        min_order_amount="0",
    )
    member_c = login("user_c", SEED_PASSWORD)[1]["access_token"]
    code3 = req("POST", "/api/coupons/claim", {"campaign_id": disc2["id"]}, member_c)[1]["coupon"][
        "code"
    ]
    s, d2 = req(
        "POST", "/api/redemptions", {"code": code3, "order_amount": "1000.00"}, verifier_token
    )
    check(
        "折扣券受封顶约束",
        Decimal(str(d2.get("discount_amount"))) == Decimal("50.00"),
        f"1000 元 8.5 折本应优惠 150，封顶后 {d2.get('discount_amount')}",
    )

    # 券型混填校验
    s, bad = req(
        "POST",
        "/api/campaigns",
        {
            "name": "非法折扣券",
            "category": "FOOD",
            "coupon_type": "DISCOUNT",
            "discount_percent": 85,
            "min_order_amount": "0",
            "total_stock": 1,
            "start_at": dt.datetime.now(dt.UTC).isoformat(),
            "end_at": (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat(),
            "validity_minutes": 60,
            "per_user_limit": 1,
        },
        op,
    )
    check("折扣券缺封顶被拒绝", s == 400, str(bad.get("message"))[:40])

    # ---------- 不变量 ----------
    print("\n不变量对账")
    s, integ = req("GET", "/api/stats/integrity", token=admin)
    check("库存守恒与券的完全划分", integ.get("ok") is True, str(integ))

    print("\n" + "=" * 60)
    if problems:
        print(f"未通过 {len(problems)} 项：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("产品化改造四条流程全部通过：注册、审核、门店归属、券型与门槛")
    return 0


if __name__ == "__main__":
    sys.exit(main())
