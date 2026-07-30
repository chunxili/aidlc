"""T-10 验证：统计口径、异常指标、对账端点（FR-030/031、NFR-009、INV-1/INV-2）。"""

from __future__ import annotations

from sqlalchemy import text

from app.config import get_settings
from .conftest import auth_headers, create_campaign


def _claim(client, headers, cid):
    return client.post("/api/coupons/claim", json={"campaign_id": cid}, headers=headers)


def test_stats_match_raw_sql(client, op_headers, admin_headers, verifier_headers, db):
    """AC-1：面板数字与直接 SQL 查询完全一致（无中间缓存层）。"""
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    for i in range(1, 5):
        _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])
    code = client.get("/api/coupons/my", headers=auth_headers(client, "user001")).json()["items"][0]["code"]
    client.post("/api/redemptions", json={"code": code}, headers=verifier_headers)

    api = client.get(f"/api/stats/campaigns/{c['id']}", headers=admin_headers).json()
    raw = db.execute(
        text(
            "SELECT c.claimed_count,"
            "       count(uc.id) FILTER (WHERE uc.status='USED'),"
            "       count(uc.id) FILTER (WHERE uc.status='UNUSED' AND uc.expires_at > now()),"
            "       count(uc.id) FILTER (WHERE uc.status='UNUSED' AND uc.expires_at <= now())"
            "  FROM campaigns c LEFT JOIN user_coupons uc ON uc.campaign_id = c.id"
            " WHERE c.id = :cid GROUP BY c.id"
        ),
        {"cid": c["id"]},
    ).one()
    assert (api["claimed_count"], api["used_count"], api["active_count"], api["expired_count"]) == raw


def test_inv1_and_inv2_hold(client, op_headers, admin_headers, db):
    """AC-2/AC-3：两条对账恒等式任意时刻成立。"""
    c = create_campaign(client, op_headers, total_stock=6, per_user_limit=1)
    for i in range(1, 5):
        _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])

    s = client.get(f"/api/stats/campaigns/{c['id']}", headers=admin_headers).json()
    assert s["total_stock"] == s["claimed_count"] + s["remaining_stock"], "INV-1 不成立"
    assert s["claimed_count"] == s["used_count"] + s["active_count"] + s["expired_count"], (
        "INV-2 不成立"
    )


def test_rate_basis_and_denominators(client, op_headers, admin_headers, verifier_headers):
    """AC-4/AC-5：口径说明字段存在；claimed_count=0 时 redeem_rate 为 null。"""
    empty = create_campaign(client, op_headers, total_stock=10)
    s = client.get(f"/api/stats/campaigns/{empty['id']}", headers=admin_headers).json()
    assert s["redeem_rate"] is None, "claimed_count=0 时应为 null，不能是 0"
    assert s["claim_rate"] == 0.0
    assert "库存总量" in s["claim_rate_basis"]
    assert "已领取数" in s["redeem_rate_basis"]

    # 领 4 张核销 1 张：claim_rate = 4/10，redeem_rate = 1/4
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    for i in range(1, 5):
        _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])
    code = client.get(
        "/api/coupons/my", headers=auth_headers(client, "user001")
    ).json()["items"][0]["code"]
    client.post("/api/redemptions", json={"code": code}, headers=verifier_headers)

    s = client.get(f"/api/stats/campaigns/{c['id']}", headers=admin_headers).json()
    assert s["claim_rate"] == 0.4, s
    assert s["redeem_rate"] == 0.25, s


def test_expired_count_is_lazy(client, op_headers, admin_headers, user_a_headers, db):
    """过期数由 expires_at 实时比较得出，无需任何后台任务。"""
    c = create_campaign(client, op_headers, total_stock=10)
    _claim(client, user_a_headers, c["id"])
    before = client.get(f"/api/stats/campaigns/{c['id']}", headers=admin_headers).json()
    assert before["active_count"] == 1 and before["expired_count"] == 0

    db.execute(
        text("UPDATE user_coupons SET expires_at = now() - interval '1 s' WHERE campaign_id = :cid"),
        {"cid": c["id"]},
    )
    db.commit()

    after = client.get(f"/api/stats/campaigns/{c['id']}", headers=admin_headers).json()
    assert after["active_count"] == 0 and after["expired_count"] == 1
    assert after["claimed_count"] == 1, "过期不应改变已领取数"


def test_overview_exception_metrics(client, op_headers, admin_headers, db):
    """AC-6：SC-006 执行后 risk_blocked_24h 增量等于被拦请求数。"""
    before = client.get("/api/stats/overview", headers=admin_headers).json()
    assert before["risk_blocked_24h"] == 0

    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user160")
    for _ in range(get_settings().risk_hard_threshold + 5):
        _claim(client, headers, c["id"])

    after = client.get("/api/stats/overview", headers=admin_headers).json()
    events = db.execute(
        text(
            "SELECT count(*) FROM risk_events"
            " WHERE decision IN ('BLOCK','MANUAL_REVIEW')"
            "   AND created_at >= now() - interval '24 hours'"
        )
    ).scalar_one()
    assert after["risk_blocked_24h"] == events
    assert after["risk_blocked_24h"] > 0, "高频请求后拦截计数未增长"
    assert after["risk_pending_count"] > 0


def test_integrity_endpoint_ok(client, op_headers, admin_headers):
    """AC-7：对账端点返回 ok=true —— 让不变量成为可点击的证据。"""
    c = create_campaign(client, op_headers, total_stock=5, per_user_limit=1)
    for i in range(1, 4):
        _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])

    r = client.get("/api/stats/integrity", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["inv1_stock_overflow_count"] == 0
    assert body["inv2_mismatch_campaign_ids"] == []
    assert body["ok"] is True


def test_integrity_detects_injected_violation(client, op_headers, admin_headers, db):
    """对账端点必须真的能发现问题，而不是永远返回 ok。

    直接篡改 claimed_count 制造 INV-2 不一致（绕过 CHECK 的范围内）。
    """
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    _claim(client, auth_headers(client, "user001"), c["id"])
    db.execute(
        text("UPDATE campaigns SET claimed_count = 3 WHERE id = :cid"), {"cid": c["id"]}
    )
    db.commit()

    body = client.get("/api/stats/integrity", headers=admin_headers).json()
    assert c["id"] in body["inv2_mismatch_campaign_ids"], "对账端点没能发现被注入的不一致"
    assert body["ok"] is False


def test_verifier_cannot_read_stats(client, verifier_headers):
    """AC-8：VERIFIER 调用统计接口返回 403。"""
    for path in ("/api/stats/overview", "/api/stats/integrity"):
        r = client.get(path, headers=verifier_headers)
        assert r.status_code == 403
        assert r.json()["code"] == "FORBIDDEN"
