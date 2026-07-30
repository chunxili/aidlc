"""T-03 验证：认证与 seed（FR-060、FR-062）。"""

from __future__ import annotations

import jwt
from sqlalchemy import text

from app.config import get_settings
from app.seed import DEFAULT_PASSWORD


def test_four_roles_can_login_with_correct_role(client):
    """AC-1：四类角色各能登录并取得含正确 role 的 token。"""
    expected = {
        "op001": "OPERATOR",
        "user_a": "USER",
        "verifier001": "VERIFIER",
        "admin001": "ADMIN",
    }
    settings = get_settings()
    for username, role in expected.items():
        r = client.post(
            "/api/auth/login", json={"username": username, "password": DEFAULT_PASSWORD}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["role"] == role
        payload = jwt.decode(
            body["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        assert payload["role"] == role
        assert payload["sub"] == str(body["user"]["id"])


def test_me_restores_session(client, user_a_headers):
    """AC-1：GET /me 可恢复登录态。"""
    r = client.get("/api/auth/me", headers=user_a_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "user_a"


def test_login_unknown_user_and_wrong_password_are_indistinguishable(client):
    """账号不存在与口令错误必须返回同一个 401。

    区分二者会把"哪些账号存在"泄露给探测者。
    """
    unknown = client.post(
        "/api/auth/login", json={"username": "no_such_user", "password": DEFAULT_PASSWORD}
    )
    wrong = client.post(
        "/api/auth/login", json={"username": "user_a", "password": "wrong-password"}
    )
    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_login_requires_password(client):
    r = client.post("/api/auth/login", json={"username": "user_a"})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_no_token_401(client):
    """AC-2：无 token 访问受保护接口返回 401。"""
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


def test_tampered_signature_401(client, user_a_headers):
    """AC-2：篡改签名返回 401。"""
    token = user_a_headers["Authorization"].split()[1]
    tampered = token[:-4] + ("abcd" if not token.endswith("abcd") else "efgh")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


def test_token_signed_with_wrong_secret_401(client):
    """用别的密钥签发的 token 必须被拒绝。"""
    forged = jwt.encode({"sub": "1", "role": "ADMIN"}, "not-the-secret", algorithm="HS256")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_seed_creates_enough_users_and_is_idempotent(db):
    """AC-3：普通用户 ≥200；重复 seed 不产生重复。

    批量用户不是便利设施：FR-010 AC-1 要求 N+1 个不同用户并发领取。
    """
    from app.seed import seed_users

    count_before = db.execute(
        text("SELECT count(*) FROM users WHERE role = 'USER'")
    ).scalar_one()
    assert count_before >= 200

    total_before = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    seed_users(db, normal_user_count=210)
    total_after = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    assert total_after == total_before, "重复 seed 产生了新用户，幂等性失效"


def test_named_demo_users_exist(db):
    """竞赛演示流程需要 user_a/user_b/user_c 三个具名普通用户。"""
    rows = db.execute(
        text("SELECT username FROM users WHERE username IN ('user_a','user_b','user_c')")
    ).scalars().all()
    assert sorted(rows) == ["user_a", "user_b", "user_c"]
