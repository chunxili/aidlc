"""管理员人员名册与下钻（FR-069 ~ FR-071，CR-002）。

用 no_ai_credentials 固定在无凭证下跑：这些用例验的是聚合口径与权限，
与 AI 无关；配了真实凭证时灰区调用会引入秒级等待，让用例变慢且不稳。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from .conftest import auth_headers, create_campaign, redeem


def _claim(client, headers, campaign_id: int) -> str:
    r = client.post("/api/coupons/claim", json={"campaign_id": campaign_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["coupon"]["code"]


def _find(rows: list[dict], username: str) -> dict:
    match = [r for r in rows if r["username"] == username]
    assert match, f"名册中未找到 {username}"
    return match[0]


# ---------- 运营人员名册（FR-069）----------

def test_operator_roster_lists_all_operators(client, admin_headers):
    """AC-1：名册列出全部运营，含未审批的（ADR-018）。"""
    r = client.get("/api/admin/operators", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = r.json()

    # 具名种子运营均在册
    for username in ("op001", "op002", "op003"):
        assert _find(rows, username)["display_name"]

    # 待审批的申请人也在册：否则管理员会疑惑刚提交的人为何不见。
    #
    # 这里自己注册一个待审运营，而不是断言种子账号 op101 仍为 PENDING：
    # seed 刻意不把已有账号的 status 写回（否则重启会让管理员刚做完的审批凭空消失），
    # 所以种子申请人一旦在演示中被审批，就永久变成 ACTIVE。
    # 让用例依赖这种会被业务操作改变的状态，等于让它随演示进度随机失败。
    applicant = f"roster_{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/auth/register",
        json={
            "username": applicant,
            "password": "Roster@2026",
            "display_name": "名册待审运营",
            "role": "OPERATOR",
        },
    )
    assert r.status_code == 201, r.text

    rows = client.get("/api/admin/operators", headers=admin_headers).json()
    pending = _find(rows, applicant)
    assert pending["status"] == "PENDING"
    assert pending["display_name"] == "名册待审运营"
    assert pending["campaign_count"] == 0

    # 名册只含运营，不混入其他角色
    assert all(r_["id"] != 0 for r_ in rows)
    usernames = {r_["username"] for r_ in rows}
    assert "verifier001" not in usernames
    assert "user_a" not in usernames
    assert "admin001" not in usernames


def test_operator_with_no_campaign_has_null_redeem_rate(client, admin_headers):
    """AC-2：无投放时业绩为 0，核销率为 null 而不是 0。"""
    row = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op002")
    assert row["campaign_count"] == 0
    assert row["total_stock"] == 0
    assert row["claimed_count"] == 0
    assert row["used_count"] == 0
    assert row["redeem_rate"] is None


def test_operator_roster_aggregates_are_exact(
    client, admin_headers, op_headers, no_ai_credentials
):
    """AC-3：发布数、投放量、已领取、已核销、核销率逐项精确。"""
    c1 = create_campaign(client, op_headers, name="名册聚合甲", total_stock=8, per_user_limit=1)
    c2 = create_campaign(client, op_headers, name="名册聚合乙", total_stock=5, per_user_limit=1)

    codes = [_claim(client, auth_headers(client, f"user{i:03d}"), c1["id"]) for i in (1, 2, 3)]
    _claim(client, auth_headers(client, "user004"), c2["id"])

    assert redeem(client, auth_headers(client, "verifier001"), codes[0]).status_code == 200

    row = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op001")
    assert row["campaign_count"] == 2
    assert row["total_stock"] == 13  # 8 + 5，不随券数放大
    assert row["claimed_count"] == 4
    assert row["used_count"] == 1
    assert row["redeem_rate"] == round(1 / 4, 4)


def test_roster_total_stock_not_inflated_by_coupon_rows(
    client, admin_headers, op_headers, no_ai_credentials
):
    """AC-4：行放大回归。

    运营→活动、活动→券都是一对多。若把两张表放进同一次 join 再聚合，
    活动行会被券行放大，total_stock 会按券数重复累加。此处一个活动领 5 张券，
    若发生放大 total_stock 会变成 50 而不是 10（ADR-016）。
    """
    c = create_campaign(client, op_headers, name="放大回归", total_stock=10, per_user_limit=1)
    for i in range(11, 16):
        _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])

    row = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op001")
    assert row["campaign_count"] == 1
    assert row["total_stock"] == 10
    assert row["claimed_count"] == 5


# ---------- 运营发布的活动下钻（FR-071）----------

def test_operator_campaigns_drilldown(client, admin_headers, op_headers, no_ai_credentials):
    """AC-5：下钻列出该运营发布的活动，含派生状态与三项计数。"""
    c = create_campaign(client, op_headers, name="下钻活动", total_stock=6, per_user_limit=1)
    code = _claim(client, auth_headers(client, "user021"), c["id"])
    _claim(client, auth_headers(client, "user022"), c["id"])
    assert redeem(client, auth_headers(client, "verifier001"), code).status_code == 200

    op_id = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op001")["id"]
    r = client.get(f"/api/admin/operators/{op_id}/campaigns", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["operator"]["username"] == "op001"
    assert body["total"] == 1
    item = body["items"][0]
    assert item["name"] == "下钻活动"
    assert item["total_stock"] == 6
    assert item["claimed_count"] == 2
    assert item["used_count"] == 1
    assert item["remaining_stock"] == 4
    assert item["status"] == "ACTIVE"
    # 优惠描述由后端统一生成，前端不自行拼接
    assert item["benefit_text"]


def test_operator_campaigns_pagination_and_order(client, admin_headers, op_headers):
    """AC-6：按创建时间倒序，分页不重不漏。"""
    for i in range(1, 6):
        create_campaign(client, op_headers, name=f"分页活动{i}", total_stock=3)

    op_id = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op001")["id"]
    first = client.get(
        f"/api/admin/operators/{op_id}/campaigns?page=1&page_size=2", headers=admin_headers
    ).json()
    second = client.get(
        f"/api/admin/operators/{op_id}/campaigns?page=2&page_size=2", headers=admin_headers
    ).json()

    assert first["total"] == second["total"] == 5
    assert len(first["items"]) == 2 and len(second["items"]) == 2
    assert first["items"][0]["name"] == "分页活动5"  # 倒序
    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 4


def test_operator_campaigns_rejects_non_operator(client, admin_headers):
    """AC-7：目标不是运营时 404，与「不存在」同一个错误码。"""
    r = client.get("/api/admin/operators/999999999/campaigns", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["code"] == "USER_NOT_FOUND"

    verifier_id = client.get("/api/admin/verifiers", headers=admin_headers).json()[0]["id"]
    r = client.get(f"/api/admin/operators/{verifier_id}/campaigns", headers=admin_headers)
    assert r.status_code == 404


# ---------- 核销员核销记录下钻（FR-070）----------

def test_verifier_redemptions_uses_snapshot_amounts(
    client, admin_headers, op_headers, no_ai_credentials
):
    """AC-8：核销记录取落库快照，金额与应付逐项精确（ADR-017）。"""
    c = create_campaign(
        client,
        op_headers,
        name="快照校验",
        coupon_type="CASH",
        face_value="20.00",
        min_order_amount="100.00",
        total_stock=5,
    )
    code = _claim(client, auth_headers(client, "user031"), c["id"])
    assert redeem(client, auth_headers(client, "verifier001"), code, "128.00").status_code == 200

    verifiers = client.get("/api/admin/verifiers", headers=admin_headers).json()
    vid = _find(verifiers, "verifier001")["id"]
    r = client.get(f"/api/admin/verifiers/{vid}/redemptions", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["verifier"]["display_name"] == "王磊"
    assert body["verifier"]["store_name"]
    assert body["total"] == 1
    item = body["items"][0]
    assert item["code"] == code
    assert item["campaign_name"] == "快照校验"
    assert item["coupon_type"] == "CASH"
    assert Decimal(item["order_amount"]) == Decimal("128.00")
    assert Decimal(item["discount_amount"]) == Decimal("20.00")
    assert Decimal(item["payable_amount"]) == Decimal("108.00")
    assert item["store_name"]
    assert item["used_at"]


def test_verifier_redemptions_scoped_to_that_verifier(
    client, admin_headers, op_headers, no_ai_credentials
):
    """AC-9：只返回该核销员本人的核销记录。"""
    c = create_campaign(client, op_headers, name="归属校验", total_stock=5, per_user_limit=1)
    code_a = _claim(client, auth_headers(client, "user041"), c["id"])
    code_b = _claim(client, auth_headers(client, "user042"), c["id"])
    assert redeem(client, auth_headers(client, "verifier001"), code_a).status_code == 200
    assert redeem(client, auth_headers(client, "verifier002"), code_b).status_code == 200

    verifiers = client.get("/api/admin/verifiers", headers=admin_headers).json()
    v1, v2 = _find(verifiers, "verifier001")["id"], _find(verifiers, "verifier002")["id"]

    body1 = client.get(f"/api/admin/verifiers/{v1}/redemptions", headers=admin_headers).json()
    body2 = client.get(f"/api/admin/verifiers/{v2}/redemptions", headers=admin_headers).json()
    assert [i["code"] for i in body1["items"]] == [code_a]
    assert [i["code"] for i in body2["items"]] == [code_b]

    # 名册上的累计核销数与下钻的 total 必须对得上，否则两处口径不一致
    assert _find(verifiers, "verifier001")["redeemed_count"] == body1["total"]


def test_verifier_redemptions_order_and_pagination(
    client, admin_headers, op_headers, no_ai_credentials
):
    """AC-10：按核销时间倒序，分页不重不漏。"""
    c = create_campaign(client, op_headers, name="核销分页", total_stock=10, per_user_limit=1)
    codes = [_claim(client, auth_headers(client, f"user{i:03d}"), c["id"]) for i in range(51, 55)]
    vh = auth_headers(client, "verifier001")
    for code in codes:
        assert redeem(client, vh, code).status_code == 200

    vid = _find(client.get("/api/admin/verifiers", headers=admin_headers).json(), "verifier001")["id"]
    first = client.get(
        f"/api/admin/verifiers/{vid}/redemptions?page=1&page_size=2", headers=admin_headers
    ).json()
    second = client.get(
        f"/api/admin/verifiers/{vid}/redemptions?page=2&page_size=2", headers=admin_headers
    ).json()

    assert first["total"] == 4
    assert first["page"] == 1 and first["page_size"] == 2
    seen = [i["code"] for i in first["items"] + second["items"]]
    assert len(set(seen)) == 4
    assert set(seen) == set(codes)
    # 倒序：最后核销的排最前
    assert first["items"][0]["code"] == codes[-1]


def test_verifier_redemptions_page_size_capped(client, admin_headers):
    """AC-11：page_size 超上限被拒，不允许一次拉全表。"""
    vid = _find(client.get("/api/admin/verifiers", headers=admin_headers).json(), "verifier001")["id"]
    r = client.get(f"/api/admin/verifiers/{vid}/redemptions?page_size=5000", headers=admin_headers)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_verifier_redemptions_rejects_non_verifier(client, admin_headers):
    """AC-12：目标不是核销员时 404。"""
    r = client.get("/api/admin/verifiers/999999999/redemptions", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["code"] == "USER_NOT_FOUND"

    op_id = _find(client.get("/api/admin/operators", headers=admin_headers).json(), "op001")["id"]
    r = client.get(f"/api/admin/verifiers/{op_id}/redemptions", headers=admin_headers)
    assert r.status_code == 404


# ---------- 权限隔离（FR-061、SC-008）----------

def test_new_admin_endpoints_reject_non_admin(client, op_headers, verifier_headers, user_a_headers):
    """AC-13：三个新端点仅 ADMIN 可访问。"""
    paths = [
        "/api/admin/operators",
        "/api/admin/operators/1/campaigns",
        "/api/admin/verifiers/1/redemptions",
    ]
    for headers in (op_headers, verifier_headers, user_a_headers):
        for path in paths:
            r = client.get(path, headers=headers)
            assert r.status_code == 403, f"{path} 应拒绝非管理员，实际 {r.status_code}"
            assert r.json()["code"] == "FORBIDDEN"


def test_new_admin_endpoints_require_authentication(client):
    """AC-14：未登录访问返回 401。"""
    for path in (
        "/api/admin/operators",
        "/api/admin/operators/1/campaigns",
        "/api/admin/verifiers/1/redemptions",
    ):
        assert client.get(path).status_code == 401
