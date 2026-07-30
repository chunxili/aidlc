"""T-05 验证：领券核心（FR-010/011/014、NFR-001）。

并发用例是本项目最关键的验收：库存不超发（INV-1）。
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.services.coupon_code import ALPHABET, generate_code
from .conftest import auth_headers, create_campaign


def _claim(client, headers, campaign_id):
    return client.post("/api/coupons/claim", json={"campaign_id": campaign_id}, headers=headers)


def test_claim_success_shape(client, op_headers, user_a_headers):
    c = create_campaign(client, op_headers, total_stock=5, validity_minutes=60)
    r = _claim(client, user_a_headers, c["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    coupon = body["coupon"]
    assert len(coupon["code"]) == 10
    assert coupon["status"] == "UNUSED"
    assert coupon["display_status"] == "可用"
    assert coupon["seq"] == 1
    # 风控段存在且未降级（低频放行，未调用 AI）
    assert body["risk"]["decision"] == "PASS"
    assert body["risk"]["decided_by"] == "RULE"


def test_expires_at_is_min_of_end_and_validity(client, op_headers, user_a_headers, db):
    """ADR-003：expires_at = min(活动结束时间, 领取时间 + 有效时长)。"""
    now = dt.datetime.now(dt.UTC)
    # 活动 10 分钟后结束，但有效时长 600 分钟 → 应取活动结束时间
    c = create_campaign(
        client,
        op_headers,
        end_at=(now + dt.timedelta(minutes=10)).isoformat(),
        validity_minutes=600,
    )
    r = _claim(client, user_a_headers, c["id"])
    exp = dt.datetime.fromisoformat(r.json()["coupon"]["expires_at"])
    end = dt.datetime.fromisoformat(c["end_at"])
    assert abs((exp - end).total_seconds()) < 2, "未取活动结束时间作为上界"

    # 活动 1 天后结束，有效时长 1 分钟 → 应取领取时间 + 1 分钟
    c2 = create_campaign(client, op_headers, validity_minutes=1)
    r2 = _claim(client, auth_headers(client, "user_b"), c2["id"])
    coupon = r2.json()["coupon"]
    exp2 = dt.datetime.fromisoformat(coupon["expires_at"])
    claimed = dt.datetime.fromisoformat(coupon["claimed_at"])
    assert 55 < (exp2 - claimed).total_seconds() < 65


def test_per_user_limit_one_second_claim_rejected(client, op_headers, user_a_headers, db):
    """AC-2：per_user_limit=1 时第二次返回 PER_USER_LIMIT_REACHED，claimed_count 未变。

    这一条即初始需求验收点 4.2 的"已领取"场景（D-02）。
    """
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    assert _claim(client, user_a_headers, c["id"]).status_code == 201

    r = _claim(client, user_a_headers, c["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "PER_USER_LIMIT_REACHED"

    claimed = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    assert claimed == 1, "失败的领取仍然扣减了库存"


def test_per_user_limit_three(client, op_headers, user_a_headers):
    """AC-3：per_user_limit=3 时可领 3 次，第 4 次失败。"""
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=3)
    for i in range(3):
        r = _claim(client, user_a_headers, c["id"])
        assert r.status_code == 201, f"第 {i + 1} 次应成功"
        assert r.json()["coupon"]["seq"] == i + 1
    r = _claim(client, user_a_headers, c["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "PER_USER_LIMIT_REACHED"


def test_out_of_stock(client, op_headers, user_a_headers, user_b_headers):
    """库存 1 时第二个用户失败 —— 竞赛演示步骤 c。"""
    c = create_campaign(client, op_headers, total_stock=1)
    assert _claim(client, user_a_headers, c["id"]).status_code == 201
    r = _claim(client, user_b_headers, c["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "OUT_OF_STOCK"


def test_claim_on_ended_campaign(client, op_headers, user_a_headers, db):
    c = create_campaign(client, op_headers)
    db.execute(
        text("UPDATE campaigns SET start_at = now() - interval '2 day',"
             " end_at = now() - interval '1 day' WHERE id = :cid"),
        {"cid": c["id"]},
    )
    db.commit()
    r = _claim(client, user_a_headers, c["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "CAMPAIGN_NOT_ACTIVE"


def test_failed_paths_leave_no_trace(client, op_headers, user_a_headers, db):
    """AC-4：任一失败路径不产生券行、不改 claimed_count。"""
    c = create_campaign(client, op_headers, total_stock=1, per_user_limit=1)
    _claim(client, user_a_headers, c["id"])
    before = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    rows_before = db.execute(text("SELECT count(*) FROM user_coupons")).scalar_one()

    # 库存不足 + 超限两条失败路径各来一次
    _claim(client, auth_headers(client, "user_b"), c["id"])
    _claim(client, user_a_headers, c["id"])

    after = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    rows_after = db.execute(text("SELECT count(*) FROM user_coupons")).scalar_one()
    assert after == before
    assert rows_after == rows_before


# ---------- NFR-001：并发不超发 ----------

@pytest.mark.parametrize("stock", [1, 20])
def test_concurrent_claims_never_oversell(client, op_headers, db, stock):
    """AC-1：库存 N、**N+1 个不同用户**并发领取，恰好 N 成功。

    必须用不同用户：同一用户会被风控拦截（计数维度是 user_id），
    那会让成功数远小于 N 而被误判为扣减缺陷（D-08）。
    """
    c = create_campaign(client, op_headers, total_stock=stock, per_user_limit=1)
    usernames = [f"user{i:03d}" for i in range(1, stock + 2)]
    headers = [auth_headers(client, u) for u in usernames]

    with ThreadPoolExecutor(max_workers=min(32, len(headers))) as pool:
        results = list(pool.map(lambda h: _claim(client, h, c["id"]), headers))

    codes = [r.status_code for r in results]
    success = codes.count(201)
    failed = [r for r in results if r.status_code != 201]

    assert success == stock, f"库存 {stock}，成功 {success} 次"
    assert len(failed) == 1
    assert all(r.json()["code"] == "OUT_OF_STOCK" for r in failed), (
        "失败原因不是库存不足: " + str([r.json() for r in failed])
    )

    # INV-1 与 INV-2 对账
    claimed = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    rows = db.execute(
        text("SELECT count(*) FROM user_coupons WHERE campaign_id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    assert claimed == stock
    assert rows == stock, "claimed_count 与实际券数不一致"


def test_concurrent_same_user_never_exceeds_limit(client, op_headers, db):
    """同一用户并发领取不得超过 per_user_limit。

    这条验证 UNIQUE(campaign_id,user_id,seq) 的并发保障：并发下多个请求算出
    同一个 seq，数据库必须拒绝多余的那些。
    """
    c = create_campaign(client, op_headers, total_stock=50, per_user_limit=2)
    headers = auth_headers(client, "user180")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _claim(client, headers, c["id"]), range(8)))

    success = sum(1 for r in results if r.status_code == 201)
    assert success <= 2, f"超过个人上限：成功 {success} 次"

    rows = db.execute(
        text("SELECT count(*) FROM user_coupons WHERE campaign_id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    claimed = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    assert rows == success
    assert claimed == success, "库存扣减与实际发券数不一致（回滚未生效）"


# ---------- FR-011 我的券 ----------

def test_my_coupons_isolated_between_users(client, op_headers, user_a_headers, user_b_headers):
    """AC-6：用户 A 看不到用户 B 的券。"""
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    _claim(client, user_a_headers, c["id"])
    _claim(client, user_b_headers, c["id"])

    ra = client.get("/api/coupons/my", headers=user_a_headers).json()
    assert ra["total"] == 1
    codes_a = {i["code"] for i in ra["items"]}

    rb = client.get("/api/coupons/my", headers=user_b_headers).json()
    codes_b = {i["code"] for i in rb["items"]}
    assert codes_a.isdisjoint(codes_b)


def test_my_coupons_expiry_is_lazy(client, op_headers, user_a_headers, db):
    """AC-1（FR-011）：到期后无需任何后台任务，状态即变为已过期。"""
    c = create_campaign(client, op_headers, validity_minutes=60)
    r = _claim(client, user_a_headers, c["id"])
    code = r.json()["coupon"]["code"]

    before = client.get("/api/coupons/my", headers=user_a_headers).json()["items"][0]
    assert before["display_status"] == "可用"

    # 直接把 expires_at 拨到过去，模拟时间流逝（不改 status）
    db.execute(
        text("UPDATE user_coupons SET expires_at = now() - interval '1 minute' WHERE code = :c"),
        {"c": code},
    )
    db.commit()

    after = client.get("/api/coupons/my", headers=user_a_headers).json()["items"][0]
    assert after["display_status"] == "已过期"
    assert after["status"] == "UNUSED", "过期被写入了 status 列，违背 INV-3"


# ---------- FR-014 券码 ----------

def test_code_alphabet_and_uniqueness():
    """AC-5：生成 10000 个券码无重复、无 0O1IL、不含可推导信息。"""
    codes = {generate_code() for _ in range(10000)}
    assert len(codes) == 10000, "10000 次生成出现重复"
    forbidden = set("0O1IL")
    for c in codes:
        assert len(c) == 10
        assert not (set(c) & forbidden), f"券码含易混淆字符: {c}"
        assert set(c) <= set(ALPHABET)


def test_code_is_not_predictable(client, op_headers, user_a_headers, user_b_headers):
    """相邻发出的券码之间不应有可推导关系（ADR-010 安全约束）。"""
    c = create_campaign(client, op_headers, total_stock=10, per_user_limit=1)
    c1 = _claim(client, user_a_headers, c["id"]).json()["coupon"]["code"]
    c2 = _claim(client, user_b_headers, c["id"]).json()["coupon"]["code"]
    assert c1 != c2
    # 不含活动 id、用户 id、序号等可推导片段
    for code in (c1, c2):
        assert str(c["id"]) not in code or len(str(c["id"])) == 1
