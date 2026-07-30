"""T-15：运营设置、策略默认值、乐观锁与同事务审计。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.seed import (
    DEFAULT_ALERT_SETTINGS,
    DEFAULT_AUDIENCE_THRESHOLDS,
    seed_operator_settings,
)


@pytest.fixture(autouse=True)
def reset_operator_settings():
    db = SessionLocal()
    try:
        seed_operator_settings(db)
        medium_id = db.execute(
            text("SELECT id FROM risk_policies WHERE level='MEDIUM' ORDER BY id LIMIT 1")
        ).scalar_one()
        op_id = db.execute(text("SELECT id FROM users WHERE username='op001'")).scalar_one()
        db.execute(text("DELETE FROM config_change_logs"))
        db.execute(text("UPDATE risk_policies SET is_global_default=false"))
        db.execute(
            text("UPDATE risk_policies SET is_global_default=true WHERE id=:id"),
            {"id": medium_id},
        )
        db.execute(
            text(
                "UPDATE operator_settings SET audience_thresholds=CAST(:audience AS jsonb),"
                " default_risk_policy_id=:policy_id,alert_settings=CAST(:alerts AS jsonb),"
                " version=1,updated_by=:op,updated_at=now() WHERE id=1"
            ),
            {
                "audience": json.dumps(DEFAULT_AUDIENCE_THRESHOLDS),
                "policy_id": medium_id,
                "alerts": json.dumps(DEFAULT_ALERT_SETTINGS),
                "op": op_id,
            },
        )
        db.commit()
    finally:
        db.close()
    yield


def test_default_settings_are_seeded_and_seed_is_idempotent(client, op_headers):
    first = client.get("/api/operator/settings", headers=op_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["version"] == 1
    assert body["audience_thresholds"] == DEFAULT_AUDIENCE_THRESHOLDS
    assert body["default_risk_policy"]["level"] == "MEDIUM"
    assert body["default_risk_policy"]["review_threshold"] == 40
    assert body["default_risk_policy"]["block_threshold"] == 70

    db = SessionLocal()
    try:
        before = db.execute(text("SELECT count(*) FROM risk_policies")).scalar_one()
        seed_operator_settings(db)
        after = db.execute(text("SELECT count(*) FROM risk_policies")).scalar_one()
        assert before == after
    finally:
        db.close()


def test_update_audiences_increments_version_and_writes_audit(client, op_headers):
    payload = {
        "expected_version": 1,
        "thresholds": {
            **DEFAULT_AUDIENCE_THRESHOLDS,
            "new_user_days": 14,
        },
    }
    response = client.patch(
        "/api/operator/settings/audiences", json=payload, headers=op_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["audience_thresholds"]["new_user_days"] == 14

    changes = client.get("/api/operator/settings/changes", headers=op_headers)
    assert changes.status_code == 200
    assert changes.json()["total"] == 1
    row = changes.json()["items"][0]
    assert row["object_type"] == "OPERATOR_SETTINGS"
    assert row["before_data"]["audience_thresholds"]["new_user_days"] == 7
    assert row["after_data"]["audience_thresholds"]["new_user_days"] == 14
    assert row["changed_by"] == "op001"


def test_stale_version_is_rejected_without_audit(client, op_headers):
    payload = {
        "expected_version": 999,
        "thresholds": DEFAULT_AUDIENCE_THRESHOLDS,
    }
    response = client.patch(
        "/api/operator/settings/audiences", json=payload, headers=op_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFIG_VERSION_CONFLICT"

    changes = client.get("/api/operator/settings/changes", headers=op_headers).json()
    assert changes["total"] == 0


def test_invalid_audience_threshold_order_is_rejected(client, op_headers):
    thresholds = {**DEFAULT_AUDIENCE_THRESHOLDS, "low_redeem_rate": 80}
    response = client.patch(
        "/api/operator/settings/audiences",
        json={"expected_version": 1, "thresholds": thresholds},
        headers=op_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_POLICY"


def test_switch_risk_preset_and_create_custom_policy(client, op_headers):
    high = client.patch(
        "/api/operator/settings/risk",
        json={"expected_version": 1, "level": "HIGH"},
        headers=op_headers,
    )
    assert high.status_code == 200, high.text
    assert high.json()["default_risk_policy"]["level"] == "HIGH"
    assert high.json()["default_risk_policy"]["hard_rules"]["hard_threshold"] == 7

    custom = client.patch(
        "/api/operator/settings/risk",
        json={
            "expected_version": 2,
            "level": "CUSTOM",
            "custom": {
                "name": "大促保护",
                "hard_rules": {"window_seconds": 10, "hard_threshold": 5},
                "factor_weights": {
                    "frequency": 40,
                    "new_account": 15,
                    "low_redeem": 15,
                    "unused_coupons": 10,
                    "risk_history": 20,
                    "high_value": 10,
                },
                "review_threshold": 25,
                "block_threshold": 55,
            },
        },
        headers=op_headers,
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["version"] == 3
    assert custom.json()["default_risk_policy"]["level"] == "CUSTOM"
    assert custom.json()["default_risk_policy"]["review_threshold"] == 25


def test_invalid_custom_policy_is_rejected(client, op_headers):
    response = client.patch(
        "/api/operator/settings/risk",
        json={
            "expected_version": 1,
            "level": "CUSTOM",
            "custom": {
                "name": "错误策略",
                "hard_rules": {"window_seconds": 10, "hard_threshold": 5},
                "factor_weights": {
                    "frequency": 40,
                    "new_account": 15,
                    "low_redeem": 15,
                    "unused_coupons": 10,
                    "risk_history": 20,
                    "high_value": 10,
                },
                "review_threshold": 70,
                "block_threshold": 60,
            },
        },
        headers=op_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_POLICY"


def test_update_alerts_preserves_all_rules(client, op_headers):
    alerts = json.loads(json.dumps(DEFAULT_ALERT_SETTINGS))
    alerts["quota_usage"]["threshold"] = 0.9
    alerts["claim_growth"]["enabled"] = False
    response = client.patch(
        "/api/operator/settings/alerts",
        json={"expected_version": 1, "settings": alerts},
        headers=op_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["alert_settings"]["quota_usage"]["threshold"] == 0.9
    assert response.json()["alert_settings"]["claim_growth"]["enabled"] is False


def test_audit_failure_rolls_back_settings(db, monkeypatch):
    """NFR-015：配置与审计同事务，审计失败不得留下半次配置更新。"""
    from app.models import OperatorSettings
    from app.schemas import AudienceThresholds
    from app.services import operator_settings as svc

    operator_id = db.execute(
        text("SELECT id FROM users WHERE username='op001'")
    ).scalar_one()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(svc, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        svc.update_audiences(
            db,
            expected_version=1,
            thresholds=AudienceThresholds(
                **{**DEFAULT_AUDIENCE_THRESHOLDS, "new_user_days": 14}
            ),
            operator_id=operator_id,
        )
    db.rollback()

    settings = db.get(OperatorSettings, 1)
    assert settings.version == 1
    assert settings.audience_thresholds["new_user_days"] == 7
    assert db.execute(text("SELECT count(*) FROM config_change_logs")).scalar_one() == 0
