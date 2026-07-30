"""CR-001 验证：券型与使用门槛（FR-015、FR-022、ADR-013、ADR-014）。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import pricing
from .conftest import create_campaign, make_campaign_payload


def _claim(client, headers, cid):
    return client.post("/api/coupons/claim", json={"campaign_id": cid}, headers=headers)


def _redeem(client, headers, code, amount):
    return client.post(
        "/api/redemptions", json={"code": code, "order_amount": amount}, headers=headers
    )


def cash_payload(**kw):
    return make_campaign_payload(coupon_type="CASH", face_value="20.00", **kw)


def discount_payload(**kw):
    p = make_campaign_payload(
        coupon_type="DISCOUNT", discount_percent=85, max_discount_amount="50.00", **kw
    )
    p.pop("face_value", None)
    return p


# ---------- 创建活动的券型校验 ----------

def test_cash_requires_face_value(client, op_headers):
    p = cash_payload()
    p.pop("face_value")
    r = client.post("/api/campaigns", json=p, headers=op_headers)
    assert r.status_code == 400
    assert "减免金额" in r.json()["message"]


def test_discount_requires_percent_and_cap(client, op_headers):
    p = discount_payload()
    p.pop("max_discount_amount")
    r = client.post("/api/campaigns", json=p, headers=op_headers)
    assert r.status_code == 400
    # 封顶是必填而非可选：无上限的折扣券在大额订单上造成不可控的营销成本
    assert "封顶" in r.json()["message"]


def test_cash_rejects_discount_fields(client, op_headers):
    r = client.post(
        "/api/campaigns", json=cash_payload(discount_percent=80), headers=op_headers
    )
    assert r.status_code == 400


def test_discount_rejects_face_value(client, op_headers):
    p = discount_payload()
    p["face_value"] = "10.00"
    r = client.post("/api/campaigns", json=p, headers=op_headers)
    assert r.status_code == 400


def test_discount_percent_range(client, op_headers):
    for bad in (0, 100, 150):
        p = discount_payload()
        p["discount_percent"] = bad
        r = client.post("/api/campaigns", json=p, headers=op_headers)
        assert r.status_code == 400, f"discount_percent={bad} 应被拒绝"


def test_database_rejects_invalid_coupon_type_combo(db):
    """数据库层兜底：绕过应用层直接插入非法组合也必须被拒绝（ADR-013）。"""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO campaigns(name, category, coupon_type, total_stock,"
                " start_at, end_at, validity_minutes, per_user_limit)"
                " VALUES ('无面额满减券', 'FOOD', 'CASH', 1, now(),"
                "         now() + interval '1 day', 60, 1)"
            )
        )
    assert "ck_campaigns_cash_requires_face_value" in str(e.value.orig)
    db.rollback()

    with pytest.raises(IntegrityError) as e2:
        db.execute(
            text(
                "INSERT INTO campaigns(name, category, coupon_type, discount_percent,"
                " total_stock, start_at, end_at, validity_minutes, per_user_limit)"
                " VALUES ('无封顶折扣券', 'FOOD', 'DISCOUNT', 85, 1, now(),"
                "         now() + interval '1 day', 60, 1)"
            )
        )
    assert "ck_campaigns_discount_requires_percent_and_cap" in str(e2.value.orig)


# ---------- 优惠金额计算 ----------

@pytest.mark.parametrize(
    "order,expected",
    [("100.00", "20.00"), ("20.00", "20.00"), ("15.00", "15.00")],
)
def test_cash_discount_amount(client, op_headers, user_a_headers, verifier_headers, order, expected):
    """满减券的优惠额恒为减免额，但不超过订单金额本身。"""
    c = create_campaign(client, op_headers, coupon_type="CASH", face_value="20.00",
                        min_order_amount="0", total_stock=5, per_user_limit=5)
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    r = _redeem(client, verifier_headers, code, order)
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["discount_amount"]) == Decimal(expected)
    assert Decimal(body["payable_amount"]) == Decimal(order) - Decimal(expected)


def test_discount_coupon_applies_percentage(client, op_headers, user_a_headers, verifier_headers):
    """8.5 折：200 元订单优惠 30 元。"""
    c = create_campaign(
        client, op_headers, coupon_type="DISCOUNT", face_value=None,
        discount_percent=85, max_discount_amount="50.00", min_order_amount="0", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    r = _redeem(client, verifier_headers, code, "200.00")
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["discount_amount"]) == Decimal("30.00")
    assert Decimal(r.json()["payable_amount"]) == Decimal("170.00")


def test_discount_is_capped(client, op_headers, user_a_headers, verifier_headers):
    """折扣券必须受封顶约束：1000 元订单 8.5 折本应优惠 150，封顶 50 后只减 50。"""
    c = create_campaign(
        client, op_headers, coupon_type="DISCOUNT", face_value=None,
        discount_percent=85, max_discount_amount="50.00", min_order_amount="0", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    r = _redeem(client, verifier_headers, code, "1000.00")
    assert Decimal(r.json()["discount_amount"]) == Decimal("50.00")


def test_discount_rounds_down(client, op_headers, user_a_headers, verifier_headers):
    """优惠额向下取整到分：多算一分是商家吃亏。"""
    c = create_campaign(
        client, op_headers, coupon_type="DISCOUNT", face_value=None,
        discount_percent=97, max_discount_amount="100.00", min_order_amount="0", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    # 33.33 × 3% = 0.9999 → 向下取整为 0.99
    r = _redeem(client, verifier_headers, code, "33.33")
    assert Decimal(r.json()["discount_amount"]) == Decimal("0.99")


# ---------- 使用门槛（FR-022）----------

def test_below_threshold_rejected(client, op_headers, user_a_headers, verifier_headers, db):
    """未达门槛不得核销，且券必须保持未使用状态。"""
    c = create_campaign(
        client, op_headers, coupon_type="CASH", face_value="30.00",
        min_order_amount="100.00", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]

    r = _redeem(client, verifier_headers, code, "99.99")
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_AMOUNT_BELOW_THRESHOLD"
    assert "100" in r.json()["message"]

    status = db.execute(
        text("SELECT status FROM user_coupons WHERE code = :c"), {"c": code}
    ).scalar_one()
    assert status == "UNUSED", "未达门槛的失败核销消耗了券"

    # 达到门槛后可正常核销
    assert _redeem(client, verifier_headers, code, "100.00").status_code == 200


def test_terminal_state_wins_over_threshold(
    client, op_headers, user_a_headers, verifier_headers
):
    """已核销的券即使本次订单未达门槛，也应回「已核销」而非「未达门槛」。

    否则核销员会以为换个订单金额就能再用一次（ADR-014 判定顺序）。
    """
    c = create_campaign(
        client, op_headers, coupon_type="CASH", face_value="30.00",
        min_order_amount="100.00", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    assert _redeem(client, verifier_headers, code, "150.00").status_code == 200

    r = _redeem(client, verifier_headers, code, "10.00")
    assert r.json()["code"] == "COUPON_ALREADY_USED"


def test_order_amount_is_required(client, op_headers, user_a_headers, verifier_headers):
    c = create_campaign(client, op_headers, total_stock=5)
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    r = client.post("/api/redemptions", json={"code": code}, headers=verifier_headers)
    assert r.status_code == 400


def test_redemption_snapshot_is_persisted(
    client, op_headers, user_a_headers, verifier_headers, db
):
    """核销时的订单金额与优惠额必须落库：活动配置日后可能被改，不能靠现值重算。"""
    c = create_campaign(
        client, op_headers, coupon_type="CASH", face_value="20.00",
        min_order_amount="0", total_stock=5,
    )
    code = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    _redeem(client, verifier_headers, code, "88.80")

    row = db.execute(
        text(
            "SELECT order_amount, discount_amount, used_store_id"
            " FROM user_coupons WHERE code = :c"
        ),
        {"c": code},
    ).one()
    assert Decimal(row[0]) == Decimal("88.80")
    assert Decimal(row[1]) == Decimal("20.00")
    assert row[2] is not None, "未记录核销门店"


# ---------- 展示文案 ----------

def test_benefit_text_is_generated_by_backend(client, op_headers, user_a_headers):
    """优惠描述由后端统一生成，避免前后端各拼一套文案。"""
    cash = create_campaign(
        client, op_headers, name="满减券", coupon_type="CASH",
        face_value="30.00", min_order_amount="100.00", total_stock=5,
    )
    assert "满 100 减 30" in cash["benefit_text"]

    disc = create_campaign(
        client, op_headers, name="折扣券", coupon_type="DISCOUNT", face_value=None,
        discount_percent=85, max_discount_amount="50.00", min_order_amount="200.00",
        total_stock=5,
    )
    assert "8.5 折" in disc["benefit_text"]
    assert "最高减 50" in disc["benefit_text"]

    available = client.get("/api/campaigns/available", headers=user_a_headers).json()
    for item in available:
        assert item["benefit_text"], "可领列表缺少优惠描述"


def test_no_threshold_text(client, op_headers):
    c = create_campaign(
        client, op_headers, coupon_type="CASH", face_value="15.00",
        min_order_amount="0", total_stock=5,
    )
    assert c["benefit_text"] == "立减 15"


def test_pricing_unit_cases():
    """直接测算法边界，避免每次都要走一遍 HTTP。"""

    class C:
        coupon_type = "DISCOUNT"
        face_value = None
        min_order_amount = Decimal("50")
        discount_percent = 90
        max_discount_amount = Decimal("20")

    assert pricing.meets_threshold(C, Decimal("50")) is True
    assert pricing.meets_threshold(C, Decimal("49.99")) is False
    # 100 元 9 折 = 优惠 10 元，未触及 20 元封顶
    assert pricing.compute_discount(C, Decimal("100")) == Decimal("10.00")
    # 1000 元 9 折本应优惠 100，封顶 20
    assert pricing.compute_discount(C, Decimal("1000")) == Decimal("20.00")
