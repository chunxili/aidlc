"""CR-001 验证：注册、口令、账号状态与管理员审核（FR-063 ~ FR-067、NFR-012）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.passwords import hash_password, verify_password
from app.seed import DEFAULT_PASSWORD
from .conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def store_id(client):
    stores = client.get("/api/stores").json()
    assert stores, "门店主数据为空"
    return stores[0]["id"]


# ---------- 口令安全（NFR-012）----------

def test_password_hash_is_salted_and_verifiable():
    """同一口令两次杂凑必须不同（有盐），且都能校验通过。"""
    a = hash_password("Secret@123")
    b = hash_password("Secret@123")
    assert a != b, "两次杂凑相同，说明没有加盐"
    assert a.startswith("scrypt$")
    assert verify_password("Secret@123", a)
    assert verify_password("Secret@123", b)
    assert not verify_password("Secret@124", a)


def test_password_never_stored_in_plaintext(client, store_id, db):
    username, password = _uniq("plain"), "Secret@123456"
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "display_name": "明文检查",
            "role": "USER",
        },
    )
    assert r.status_code == 201, r.text
    stored = db.execute(
        text("SELECT password_hash FROM users WHERE username = :u"), {"u": username}
    ).scalar_one()
    assert password not in stored, "口令以明文出现在数据库中"
    assert stored.startswith("scrypt$")


def test_empty_stored_hash_never_authenticates():
    """历史遗留的无口令账号不得因空口令而放行。"""
    assert not verify_password("", None)
    assert not verify_password("anything", "")


# ---------- 会员注册即时启用（FR-063）----------

def test_member_registration_is_active_immediately(client):
    username = _uniq("member")
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "新会员",
            "role": "USER",
            "phone": "13700000001",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["needs_approval"] is False
    assert body["user"]["status"] == "ACTIVE"

    # 注册后可立即登录并使用业务接口
    headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/login", json={"username": username, "password": "Secret@123456"}
        ).json()["access_token"]
    }
    assert client.get("/api/coupons/my", headers=headers).status_code == 200


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/register",
        json={
            "username": _uniq("weak"),
            "password": "123",
            "display_name": "弱口令",
            "role": "USER",
        },
    )
    assert r.status_code == 400


def test_duplicate_username_rejected(client):
    username = _uniq("dup")
    payload = {
        "username": username,
        "password": "Secret@123456",
        "display_name": "重复账号",
        "role": "USER",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 201
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 409
    assert r.json()["code"] == "USERNAME_TAKEN"


def test_admin_cannot_self_register(client):
    r = client.post(
        "/api/auth/register",
        json={
            "username": _uniq("admin"),
            "password": "Secret@123456",
            "display_name": "想当管理员",
            "role": "ADMIN",
        },
    )
    # 角色不在可注册枚举内，契约层即拒绝
    assert r.status_code == 400


# ---------- 核销员注册需选门店且待审核（FR-063）----------

def test_verifier_registration_requires_store(client):
    r = client.post(
        "/api/auth/register",
        json={
            "username": _uniq("v_nostore"),
            "password": "Secret@123456",
            "display_name": "无门店核销员",
            "role": "VERIFIER",
        },
    )
    assert r.status_code == 400
    assert "门店" in r.json()["message"]


def test_non_verifier_cannot_pick_store(client, store_id):
    r = client.post(
        "/api/auth/register",
        json={
            "username": _uniq("u_store"),
            "password": "Secret@123456",
            "display_name": "会员选门店",
            "role": "USER",
            "store_id": store_id,
        },
    )
    assert r.status_code == 400


def test_verifier_and_operator_need_approval(client, store_id):
    for role, extra in [("VERIFIER", {"store_id": store_id}), ("OPERATOR", {})]:
        username = _uniq(role.lower())
        r = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": "Secret@123456",
                "display_name": f"待审{role}",
                "role": role,
                **extra,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["needs_approval"] is True
        assert r.json()["user"]["status"] == "PENDING"


# ---------- 账号状态与登录准入（FR-065、ADR-012）----------

def test_pending_can_login_but_not_use_business_api(client, store_id):
    """待审核账号可以登录看进度，但不得访问业务接口。

    不能登录会让用户无法查看申请进度，只能反复注册产生垃圾数据。
    """
    username = _uniq("pending")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "待审核",
            "role": "VERIFIER",
            "store_id": store_id,
        },
    )
    login = client.post(
        "/api/auth/login", json={"username": username, "password": "Secret@123456"}
    )
    assert login.status_code == 200, "待审核账号应能登录"
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}

    # 能查自己的状态
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["status"] == "PENDING"

    # 但业务接口被拒，且返回专用错误码供前端跳转到进度页
    biz = client.get("/api/redemptions/ABCDEFGHJK", headers=headers)
    assert biz.status_code == 403
    assert biz.json()["code"] == "ACCOUNT_PENDING_APPROVAL"


def test_rejected_cannot_login_and_may_reapply(client, store_id, admin_headers):
    username = _uniq("reject")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "将被驳回",
            "role": "OPERATOR",
        },
    )
    pending = client.get("/api/admin/registrations", headers=admin_headers).json()
    target = next(u for u in pending if u["username"] == username)

    r = client.post(
        f"/api/admin/registrations/{target['id']}/review",
        json={"approve": False, "reason": "资料不全"},
        headers=admin_headers,
    )
    assert r.status_code == 200

    login = client.post(
        "/api/auth/login", json={"username": username, "password": "Secret@123456"}
    )
    assert login.status_code == 403
    assert login.json()["code"] == "ACCOUNT_REJECTED"
    assert "资料不全" in login.json()["message"]

    # 允许用同一账号重新提交申请（更新原记录，不新建）
    again = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "补齐资料",
            "role": "OPERATOR",
        },
    )
    assert again.status_code == 201
    assert again.json()["user"]["status"] == "PENDING"


# ---------- 管理员审核（FR-066）----------

def test_approve_then_verifier_can_work(client, store_id, admin_headers):
    username = _uniq("v_ok")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "通过核销员",
            "role": "VERIFIER",
            "store_id": store_id,
        },
    )
    pending = client.get("/api/admin/registrations", headers=admin_headers).json()
    target = next(u for u in pending if u["username"] == username)
    assert target["store_name"], "待审列表应显示申请人所选门店"

    client.post(
        f"/api/admin/registrations/{target['id']}/review",
        json={"approve": True},
        headers=admin_headers,
    )
    headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/login", json={"username": username, "password": "Secret@123456"}
        ).json()["access_token"]
    }
    # 审核通过后可访问核销接口（券不存在返回 404 而非 403）
    r = client.get("/api/redemptions/ABCDEFGHJK", headers=headers)
    assert r.status_code == 404


def test_review_is_idempotent(client, admin_headers):
    username = _uniq("idem")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "Secret@123456",
            "display_name": "幂等审核",
            "role": "OPERATOR",
        },
    )
    pending = client.get("/api/admin/registrations", headers=admin_headers).json()
    target = next(u for u in pending if u["username"] == username)

    first = client.post(
        f"/api/admin/registrations/{target['id']}/review",
        json={"approve": True},
        headers=admin_headers,
    )
    second = client.post(
        f"/api/admin/registrations/{target['id']}/review",
        json={"approve": False, "reason": "改主意了"},
        headers=admin_headers,
    )
    assert first.status_code == 200 and second.status_code == 200
    # 已审过的申请不得被二次改判
    login = client.post(
        "/api/auth/login", json={"username": username, "password": "Secret@123456"}
    )
    assert login.status_code == 200, "二次审批改变了已生效的结果"


# ---------- 核销人员名册（FR-067）----------

def test_verifier_roster_lists_all_stores(client, admin_headers):
    roster = client.get("/api/admin/verifiers", headers=admin_headers).json()
    assert len(roster) >= 3, "seed 应至少有 3 名核销人员"
    for v in roster:
        assert v["store_name"] and v["store_district"] and v["store_code"]
        assert v["redeemed_count"] >= 0
    # 覆盖多个行政区
    assert len({v["store_district"] for v in roster}) >= 2


def test_verifier_roster_filter_by_district(client, admin_headers):
    roster = client.get("/api/admin/verifiers", headers=admin_headers).json()
    district = roster[0]["store_district"]
    filtered = client.get(
        f"/api/admin/verifiers?district={district}", headers=admin_headers
    ).json()
    assert filtered
    assert {v["store_district"] for v in filtered} == {district}


def test_roster_counts_redemptions(client, op_headers, user_a_headers, admin_headers):
    """名册中的累计核销数应随核销增长。"""
    from .conftest import create_campaign

    before = {
        v["username"]: v["redeemed_count"]
        for v in client.get("/api/admin/verifiers", headers=admin_headers).json()
    }
    c = create_campaign(client, op_headers, total_stock=5)
    code = client.post(
        "/api/coupons/claim", json={"campaign_id": c["id"]}, headers=user_a_headers
    ).json()["coupon"]["code"]
    client.post(
        "/api/redemptions",
        json={"code": code, "order_amount": "100.00"},
        headers=auth_headers(client, "verifier001"),
    )
    after = {
        v["username"]: v["redeemed_count"]
        for v in client.get("/api/admin/verifiers", headers=admin_headers).json()
    }
    assert after["verifier001"] == before["verifier001"] + 1


# ---------- 门店主数据（FR-068）----------

def test_stores_cover_guangzhou_districts(client):
    stores = client.get("/api/stores").json()
    districts = {s["district"] for s in stores}
    assert len(stores) >= 20
    for expected in ("天河区", "越秀区", "荔湾区", "海珠区", "番禺区"):
        assert expected in districts
    for s in stores:
        assert s["address"].startswith("广州市")


def test_store_default_password_login(client):
    """seed 账号使用统一初始口令，且该口令确实经过校验。"""
    ok = client.post(
        "/api/auth/login", json={"username": "verifier001", "password": DEFAULT_PASSWORD}
    )
    bad = client.post(
        "/api/auth/login", json={"username": "verifier001", "password": DEFAULT_PASSWORD + "x"}
    )
    assert ok.status_code == 200
    assert bad.status_code == 401
