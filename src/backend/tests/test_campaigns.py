"""T-04 验证：活动管理（FR-001/002/003）。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import text

from .conftest import create_campaign, make_campaign_payload


def test_create_does_not_pregenerate_coupons(client, op_headers, db):
    """AC-1：创建成功、claimed_count=0、且不预生成任何券（ADR-001 计数器模型）。"""
    c = create_campaign(client, op_headers, total_stock=100)
    assert c["claimed_count"] == 0
    assert c["remaining_stock"] == 100
    assert c["status"] == "ACTIVE"
    rows = db.execute(
        text("SELECT count(*) FROM user_coupons WHERE campaign_id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    assert rows == 0, "创建活动时预生成了券，违背计数器模型"


def test_create_rejects_invalid_fields(client, op_headers):
    """AC-2：total_stock=0 与 end_at<=start_at 返回 400。"""
    r = client.post("/api/campaigns", json=make_campaign_payload(total_stock=0), headers=op_headers)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"

    now = dt.datetime.now(dt.UTC)
    r = client.post(
        "/api/campaigns",
        json=make_campaign_payload(
            start_at=now.isoformat(), end_at=(now - dt.timedelta(hours=1)).isoformat()
        ),
        headers=op_headers,
    )
    assert r.status_code == 400


def test_per_user_limit_defaults_to_one(client, op_headers):
    """AC-3：不传 per_user_limit 落库为 1。"""
    payload = make_campaign_payload()
    payload.pop("per_user_limit")
    r = client.post("/api/campaigns", json=payload, headers=op_headers)
    assert r.status_code == 201
    assert r.json()["per_user_limit"] == 1


def test_stock_can_only_increase(client, op_headers):
    """AC-4：调低库存 409；调高成功且剩余库存随之增加。"""
    c = create_campaign(client, op_headers, total_stock=100)

    r = client.patch(f"/api/campaigns/{c['id']}", json={"total_stock": 50}, headers=op_headers)
    assert r.status_code == 409
    assert r.json()["code"] == "STOCK_CANNOT_DECREASE"

    r = client.patch(f"/api/campaigns/{c['id']}", json={"total_stock": 200}, headers=op_headers)
    assert r.status_code == 200
    assert r.json()["total_stock"] == 200
    assert r.json()["remaining_stock"] == 200


def test_immutable_fields_rejected(client, op_headers):
    """AC-4：face_value 与 validity_minutes 不可改。

    validity_minutes 不可改的理由：已领出券的 expires_at 已落库（ADR-003），
    改它会使同一活动内的券遵循两套规则。
    """
    c = create_campaign(client, op_headers)
    for field, value in [("face_value", "99.00"), ("validity_minutes", 999)]:
        r = client.patch(f"/api/campaigns/{c['id']}", json={field: value}, headers=op_headers)
        assert r.status_code == 400, f"{field} 应被契约层拒绝，实际 {r.status_code}"
        assert r.json()["code"] == "VALIDATION_ERROR"


def test_available_excludes_ended_and_soldout(client, op_headers, user_a_headers, db):
    """AC-5：已过期与售罄活动不出现在 USER 视图。"""
    now = dt.datetime.now(dt.UTC)
    active = create_campaign(client, op_headers, name="进行中", total_stock=5)
    ended = create_campaign(
        client,
        op_headers,
        name="已结束",
        start_at=(now - dt.timedelta(days=2)).isoformat(),
        end_at=(now - dt.timedelta(days=1)).isoformat(),
    )
    soldout = create_campaign(client, op_headers, name="售罄", total_stock=1)
    db.execute(
        text("UPDATE campaigns SET claimed_count = total_stock WHERE id = :cid"),
        {"cid": soldout["id"]},
    )
    db.commit()

    r = client.get("/api/campaigns/available", headers=user_a_headers)
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert active["id"] in ids
    assert ended["id"] not in ids, "已结束活动出现在可领列表"
    assert soldout["id"] not in ids, "售罄活动出现在可领列表"


def test_available_hides_privileged_fields(client, op_headers, user_a_headers):
    """USER 视图不下发统计与风控字段（最小权限）。"""
    create_campaign(client, op_headers)
    r = client.get("/api/campaigns/available", headers=user_a_headers)
    item = r.json()[0]
    for forbidden in ("claimed_count", "total_stock"):
        assert forbidden not in item, f"USER 视图泄露了 {forbidden}"
    assert "my_claimed_count" in item


def test_status_is_derived_from_time_not_stored(client, op_headers, db):
    """AC-6：派生状态与 now() 一致，且数据库中不存在 status 列（ADR-002）。"""
    now = dt.datetime.now(dt.UTC)
    pending = create_campaign(
        client,
        op_headers,
        start_at=(now + dt.timedelta(hours=1)).isoformat(),
        end_at=(now + dt.timedelta(days=1)).isoformat(),
    )
    assert pending["status"] == "PENDING"

    ended = create_campaign(
        client,
        op_headers,
        start_at=(now - dt.timedelta(days=2)).isoformat(),
        end_at=(now - dt.timedelta(days=1)).isoformat(),
    )
    assert ended["status"] == "ENDED"

    cols = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'campaigns'"
        )
    ).scalars().all()
    assert "status" not in cols, "活动状态被落库了，违背 ADR-002"
    assert "remaining_stock" not in cols, "剩余库存被落库了，它是恒等式"
