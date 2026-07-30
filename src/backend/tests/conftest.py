"""测试公共设施。

测试直接打真实 PostgreSQL，不用 SQLite 替身：本项目的核心保障是数据库约束
与并发语义（ADR-001），换库等于不验证。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.main import app
from app.seed import DEFAULT_PASSWORD, seed_stores, seed_users


@pytest.fixture(scope="session", autouse=True)
def _seed_once():
    db = SessionLocal()
    try:
        # 门店须先于用户：核销员账号引用门店编码
        seed_stores(db)
        # 测试只需少量批量用户；并发验收脚本另行使用完整 seed。
        seed_users(db, normal_user_count=210)
    finally:
        db.close()


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(autouse=True)
def clean_business_data():
    """每个用例前清业务数据，保留用户。

    不清 users：seed 是幂等的且用户是测试的公共前提，反复重建只是浪费。
    """
    session = SessionLocal()
    try:
        session.execute(text("DELETE FROM user_coupons"))
        session.execute(text("DELETE FROM risk_events"))
        session.execute(text("DELETE FROM ai_invocations"))
        session.execute(text("DELETE FROM campaigns"))
        session.execute(text("UPDATE users SET risk_blocked = false WHERE risk_blocked"))
        session.commit()
    finally:
        session.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def no_ai_credentials():
    """强制进入 AI 降级模式。

    验证降级行为的用例必须显式控制凭证状态，不能依赖"运行环境恰好没有凭证"：
    否则同一套测试在配了 .env 的机器上会失败，而失败原因与被测行为无关。
    """
    from app.config import get_settings
    from app.services import bedrock

    settings = get_settings()
    original = settings.aws_bearer_token_bedrock
    object.__setattr__(settings, "aws_bearer_token_bedrock", "")
    bedrock.reset_client()
    yield
    object.__setattr__(settings, "aws_bearer_token_bedrock", original)
    bedrock.reset_client()


def token_for(client: TestClient, username: str) -> str:
    r = client.post(
        "/api/auth/login", json={"username": username, "password": DEFAULT_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, username)}"}


@pytest.fixture
def op_headers(client):
    return auth_headers(client, "op001")


@pytest.fixture
def user_a_headers(client):
    return auth_headers(client, "user_a")


@pytest.fixture
def user_b_headers(client):
    return auth_headers(client, "user_b")


@pytest.fixture
def verifier_headers(client):
    return auth_headers(client, "verifier001")


@pytest.fixture
def admin_headers(client):
    return auth_headers(client, "admin001")


def make_campaign_payload(**overrides) -> dict:
    """默认造一张无门槛的满减券，便于既有用例不必关心券型。"""
    now = dt.datetime.now(dt.UTC)
    payload = {
        "name": "测试活动",
        "category": "FOOD",
        "coupon_type": "CASH",
        "face_value": "20.00",
        "min_order_amount": "0",
        "total_stock": 5,
        "start_at": (now - dt.timedelta(minutes=1)).isoformat(),
        "end_at": (now + dt.timedelta(days=1)).isoformat(),
        "validity_minutes": 60,
        "per_user_limit": 1,
    }
    payload.update(overrides)
    return payload


def create_campaign(client: TestClient, op_headers: dict, **overrides) -> dict:
    r = client.post("/api/campaigns", json=make_campaign_payload(**overrides), headers=op_headers)
    assert r.status_code == 201, r.text
    return r.json()


def redeem(client: TestClient, headers: dict, code: str, order_amount: str = "100.00"):
    """核销。引入券型后订单金额必填（ADR-014），默认给一个足够大的金额。"""
    return client.post(
        "/api/redemptions", json={"code": code, "order_amount": order_amount}, headers=headers
    )


__all__ = [
    "DEFAULT_PASSWORD",
    "Decimal",
    "auth_headers",
    "create_campaign",
    "make_campaign_payload",
    "redeem",
    "token_for",
]
