"""T-03 验证：接口级角色权限（FR-061、SC-008）。

参数化覆盖 api-specification.md 第十节的路由-角色映射表全表。
这是唯一能证明"四类角色"在后端真实隔离、而非四个前端页面的验证。
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers

# (方法, 路径, 允许的角色集合)
ROUTE_MATRIX = [
    ("POST", "/api/campaigns", {"OPERATOR"}),
    ("PATCH", "/api/campaigns/1", {"OPERATOR"}),
    ("GET", "/api/campaigns", {"OPERATOR", "ADMIN"}),
    ("GET", "/api/campaigns/1", {"OPERATOR", "ADMIN"}),
    ("GET", "/api/campaigns/available", {"USER"}),
    ("POST", "/api/coupons/claim", {"USER"}),
    ("GET", "/api/coupons/my", {"USER"}),
    ("GET", "/api/recommendations", {"USER"}),
    ("GET", "/api/redemptions/ABCDEFGHJK", {"VERIFIER"}),
    ("POST", "/api/redemptions", {"VERIFIER"}),
    ("GET", "/api/risk/events", {"OPERATOR"}),
    ("POST", "/api/risk/events/1/handle", {"OPERATOR"}),
    ("GET", "/api/stats/campaigns/1", {"ADMIN", "OPERATOR"}),
    ("GET", "/api/stats/overview", {"ADMIN"}),
    ("GET", "/api/stats/integrity", {"ADMIN"}),
]

ROLE_ACCOUNTS = {
    "OPERATOR": "op001",
    "USER": "user_a",
    "VERIFIER": "verifier001",
    "ADMIN": "admin001",
}

# 每个路由 × 每个不被允许的角色 → 必须 403
FORBIDDEN_CASES = [
    (method, path, role)
    for method, path, allowed in ROUTE_MATRIX
    for role in ROLE_ACCOUNTS
    if role not in allowed
]


@pytest.mark.parametrize("method,path,role", FORBIDDEN_CASES)
def test_role_matrix_forbids_others(client, method, path, role):
    headers = auth_headers(client, ROLE_ACCOUNTS[role])
    r = client.request(method, path, headers=headers, json={})
    assert r.status_code == 403, (
        f"{role} 访问 {method} {path} 返回 {r.status_code}，应为 403"
    )
    body = r.json()
    assert body["code"] == "FORBIDDEN"
    # AC-5：越权响应体不含目标资源的任何字段
    assert set(body.keys()) <= {"code", "message"}, f"越权响应泄露了字段: {body}"


@pytest.mark.parametrize("method,path,allowed", ROUTE_MATRIX)
def test_allowed_roles_pass_authorization(client, method, path, allowed):
    """允许的角色必须通过授权检查（可能因资源不存在返回 4xx，但不能是 403）。"""
    for role in allowed:
        headers = auth_headers(client, ROLE_ACCOUNTS[role])
        r = client.request(method, path, headers=headers, json={})
        assert r.status_code != 403, (
            f"{role} 本应可访问 {method} {path}，却被拒绝"
        )


@pytest.mark.parametrize("method,path,_allowed", ROUTE_MATRIX)
def test_all_routes_require_authentication(client, method, path, _allowed):
    r = client.request(method, path, json={})
    assert r.status_code == 401, f"{method} {path} 未认证却返回 {r.status_code}"


def test_health_and_login_are_public(client):
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/login", json={"username": "user_a"}).status_code == 200
