"""T-06 验证：核销幂等与终态优先（FR-020/021、NFR-002、SC-003、SC-004）。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from .conftest import auth_headers, create_campaign


def _claim_code(client, op_headers, user_headers, **kw) -> tuple[str, dict]:
    c = create_campaign(client, op_headers, **kw)
    r = client.post("/api/coupons/claim", json={"campaign_id": c["id"]}, headers=user_headers)
    assert r.status_code == 201, r.text
    return r.json()["coupon"]["code"], c


def test_redeem_then_repeat_is_idempotent(client, op_headers, user_a_headers, verifier_headers):
    """AC-1：首次成功；第 2/3/4 次返回"已核销"且响应体逐字节一致（SC-004）。"""
    code, _ = _claim_code(client, op_headers, user_a_headers)

    first = client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    assert first.status_code == 200, first.text
    # used_by 回传核销人姓名而非账号名：界面上展示给门店人员看的是姓名
    assert first.json()["used_by"] == "王磊"
    assert first.json()["store_name"], "核销结果应带核销门店"

    repeats = [
        client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
        for _ in range(3)
    ]
    for r in repeats:
        assert r.status_code == 409
        assert r.json()["code"] == "COUPON_ALREADY_USED"
        assert r.json()["message"] == "已核销"
    # 逐字节一致
    assert len({r.content for r in repeats}) == 1


def test_used_audit_fields_written_once(client, op_headers, user_a_headers, verifier_headers, db):
    code, _ = _claim_code(client, op_headers, user_a_headers)
    client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    row1 = db.execute(
        text("SELECT used_at, used_by FROM user_coupons WHERE code = :c"), {"c": code}
    ).one()
    for _ in range(3):
        client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    row2 = db.execute(
        text("SELECT used_at, used_by FROM user_coupons WHERE code = :c"), {"c": code}
    ).one()
    assert row1 == row2, "重复核销改写了审计字段"


def test_expired_coupon_cannot_be_redeemed(client, op_headers, user_a_headers, verifier_headers, db):
    """AC-2：过期券核销返回"券已过期"（SC-003）。

    真实演示走 validity_minutes=1 等待过期；测试中拨动 expires_at 以免等待，
    但**不触碰 status** —— 过期必须是时间的函数（ADR-002）。
    """
    code, _ = _claim_code(client, op_headers, user_a_headers, validity_minutes=1)
    db.execute(
        text("UPDATE user_coupons SET expires_at = now() - interval '1 second' WHERE code = :c"),
        {"c": code},
    )
    db.commit()

    r = client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    assert r.status_code == 409
    assert r.json()["code"] == "COUPON_EXPIRED"
    assert r.json()["message"] == "券已过期"

    status = db.execute(
        text("SELECT status FROM user_coupons WHERE code = :c"), {"c": code}
    ).scalar_one()
    assert status == "UNUSED", "过期被写入 status，违背 INV-3"


def test_terminal_state_wins_over_expiry(
    client, op_headers, user_a_headers, verifier_headers, db
):
    """AC-3：已核销的券过期后再核销，返回"已核销"而非"券已过期"（终态优先）。

    这是 ADR-004 的核心：回"券已过期"会让核销员以为该券未被使用过。
    """
    code, _ = _claim_code(client, op_headers, user_a_headers)
    assert client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers).status_code == 200

    db.execute(
        text("UPDATE user_coupons SET expires_at = now() - interval '1 hour' WHERE code = :c"),
        {"c": code},
    )
    db.commit()

    r = client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    assert r.json()["code"] == "COUPON_ALREADY_USED", "终态优先失效"


def test_unknown_code_404(client, verifier_headers):
    r = client.post("/api/redemptions", json={"code": "ZZZZZZZZZZ", "order_amount": "100.00"}, headers=verifier_headers)
    assert r.status_code == 404
    assert r.json()["code"] == "COUPON_NOT_FOUND"


def test_concurrent_redeem_only_one_succeeds(
    client, op_headers, user_a_headers, verifier_headers, db
):
    """AC-4：并发 20 次核销同一券码，恰好 1 次成功。"""
    code, _ = _claim_code(client, op_headers, user_a_headers)

    def hit(_):
        return client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(hit, range(20)))

    success = sum(1 for r in results if r.status_code == 200)
    assert success == 1, f"成功次数为 {success}，幂等失效"
    others = [r.json()["code"] for r in results if r.status_code != 200]
    assert set(others) == {"COUPON_ALREADY_USED"}


def test_check_is_read_only_and_consistent(
    client, op_headers, user_a_headers, verifier_headers, db
):
    """AC-5：查验连续 10 次状态不变，且判定与核销一致。"""
    code, campaign = _claim_code(client, op_headers, user_a_headers)

    for _ in range(10):
        r = client.get(f"/api/redemptions/{code}", headers=verifier_headers)
        assert r.status_code == 200
        assert r.json()["redeemable"] is True
        assert r.json()["reason"] is None
    status = db.execute(
        text("SELECT status FROM user_coupons WHERE code = :c"), {"c": code}
    ).scalar_one()
    assert status == "UNUSED", "查验改变了券状态"

    # 过期后查验的 reason 与核销返回的口径一致
    db.execute(
        text("UPDATE user_coupons SET expires_at = now() - interval '1 s' WHERE code = :c"),
        {"c": code},
    )
    db.commit()
    check = client.get(f"/api/redemptions/{code}", headers=verifier_headers).json()
    assert check["redeemable"] is False
    assert check["reason"] == "券已过期"
    post = client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=verifier_headers)
    assert post.json()["message"] == check["reason"]


def test_owner_is_masked_in_check(client, op_headers, user_a_headers, verifier_headers):
    code, _ = _claim_code(client, op_headers, user_a_headers)
    r = client.get(f"/api/redemptions/{code}", headers=verifier_headers)
    assert r.json()["owner"] != "user_a"
    assert "***" in r.json()["owner"]


def test_non_verifier_roles_forbidden(client, op_headers, user_a_headers, admin_headers):
    """AC-6：USER/OPERATOR/ADMIN 调用核销返回 403。"""
    code, _ = _claim_code(client, op_headers, user_a_headers)
    for headers in (user_a_headers, op_headers, admin_headers):
        r = client.post("/api/redemptions", json={"code": code, "order_amount": "100.00"}, headers=headers)
        assert r.status_code == 403
        assert r.json()["code"] == "FORBIDDEN"
        # 越权响应体不得泄露券的任何字段
        assert "face_value" not in r.json()
