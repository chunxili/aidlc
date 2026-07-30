"""T-02 验证：三条不变量由数据库强制，而非应用层自觉。

这些测试刻意用原生 SQL 绕过 ORM 与业务逻辑，直接冲撞数据库约束。
断言不只检查"失败了"，而是检查**失败原因是指定的那个约束** —— 否则一个 SQL
语法错误也会让测试变绿，这类假通过比不测更危险。
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal


def _violates(exc: IntegrityError, constraint: str) -> bool:
    return constraint in str(exc.orig)


@pytest.fixture
def db():
    session = SessionLocal()
    session.execute(text("DELETE FROM user_coupons"))
    session.execute(text("DELETE FROM risk_events"))
    session.execute(text("DELETE FROM ai_invocations"))
    session.execute(text("DELETE FROM campaigns"))
    session.execute(text("DELETE FROM users WHERE username LIKE 'ct_%'"))
    session.commit()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def fixture_ids(db):
    """建一个用户与一个 total_stock=5 的活动，返回其真实 id。

    不硬编码 id：上一轮验证正因取到空 id 而把语法错误误判为约束生效。
    """
    uid = db.execute(
        text(
            "INSERT INTO users(username, display_name, role)"
            " VALUES ('ct_user', 'ct', 'USER') RETURNING id"
        )
    ).scalar_one()
    cid = db.execute(
        text(
            "INSERT INTO campaigns(name, category, face_value, total_stock, claimed_count,"
            " start_at, end_at, validity_minutes, per_user_limit)"
            " VALUES ('ct_ok', 'FOOD', 10, 5, 0, now(), now() + interval '1 day', 60, 1)"
            " RETURNING id"
        )
    ).scalar_one()
    db.commit()
    assert isinstance(uid, int) and isinstance(cid, int)
    return uid, cid


# ---------- INV-1：库存守恒 ----------

def test_insert_oversell_rejected(db):
    """AC-2：claimed_count > total_stock 在 INSERT 时被拒绝。"""
    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO campaigns(name, category, face_value, total_stock, claimed_count,"
                " start_at, end_at, validity_minutes, per_user_limit)"
                " VALUES ('ct_oversell', 'FOOD', 10, 1, 2, now(), now() + interval '1 day', 60, 1)"
            )
        )
    assert _violates(e.value, "ck_campaigns_no_oversell")


def test_update_oversell_rejected(db, fixture_ids):
    """AC-2 补充：UPDATE 路径同样被拒绝。

    这一条比 INSERT 更重要：领券的库存扣减走的正是 UPDATE。
    """
    _, cid = fixture_ids
    with pytest.raises(IntegrityError) as e:
        db.execute(text("UPDATE campaigns SET claimed_count = 6 WHERE id = :cid"), {"cid": cid})
    assert _violates(e.value, "ck_campaigns_no_oversell")


def test_time_window_rejected(db):
    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO campaigns(name, category, face_value, total_stock,"
                " start_at, end_at, validity_minutes, per_user_limit)"
                " VALUES ('ct_badwin', 'FOOD', 10, 1, now(), now() - interval '1 day', 60, 1)"
            )
        )
    assert _violates(e.value, "ck_campaigns_time_window")


def test_bad_category_rejected(db):
    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO campaigns(name, category, face_value, total_stock,"
                " start_at, end_at, validity_minutes, per_user_limit)"
                " VALUES ('ct_badcat', 'NOPE', 10, 1, now(), now() + interval '1 day', 60, 1)"
            )
        )
    assert _violates(e.value, "ck_campaigns_category")


# ---------- 限领的并发保障 ----------

def _insert_coupon(db, cid: int, uid: int, seq: int, code: str, **extra):
    cols = "campaign_id, user_id, seq, code, status, expires_at"
    vals = ":cid, :uid, :seq, :code, :status, now() + interval '1 hour'"
    params = {"cid": cid, "uid": uid, "seq": seq, "code": code, "status": extra.pop("status", "UNUSED")}
    for k, v in extra.items():
        cols += f", {k}"
        vals += f", :{k}"
        params[k] = v
    return db.execute(text(f"INSERT INTO user_coupons({cols}) VALUES ({vals})"), params)


def test_duplicate_seq_rejected(db, fixture_ids):
    """AC-3：重复 (campaign_id, user_id, seq) 被唯一索引拒绝。

    这条索引就是"每用户限领数"的并发保障（ADR-001）：并发下两个请求算出同一个
    seq，数据库拒绝其一，触发回滚，claimed_count 的 +1 随之撤销。
    """
    uid, cid = fixture_ids
    _insert_coupon(db, cid, uid, 1, "ABCDEFGHJK")
    db.commit()
    with pytest.raises(IntegrityError) as e:
        _insert_coupon(db, cid, uid, 1, "MNPQRSTVWX")
    assert _violates(e.value, "uq_user_coupons_campaign_user_seq")


def test_duplicate_code_rejected(db, fixture_ids):
    uid, cid = fixture_ids
    _insert_coupon(db, cid, uid, 1, "ABCDEFGHJK")
    db.commit()
    with pytest.raises(IntegrityError) as e:
        _insert_coupon(db, cid, uid, 2, "ABCDEFGHJK")
    assert _violates(e.value, "user_coupons_code_key")


# ---------- INV-3：状态两态与核销字段一致性 ----------

def test_used_without_audit_fields_rejected(db, fixture_ids):
    uid, cid = fixture_ids
    with pytest.raises(IntegrityError) as e:
        _insert_coupon(db, cid, uid, 1, "USEDNOAUD1", status="USED")
    assert _violates(e.value, "ck_user_coupons_used_consistency")


def test_unused_with_audit_fields_rejected(db, fixture_ids):
    uid, cid = fixture_ids
    with pytest.raises(IntegrityError) as e:
        _insert_coupon(
            db, cid, uid, 1, "UNUSEDAUD1", used_at=dt.datetime.now(dt.UTC), used_by=uid
        )
    assert _violates(e.value, "ck_user_coupons_used_consistency")


def test_expired_status_rejected(db, fixture_ids):
    """"已过期"不是存储状态（INV-3、ADR-002），数据库必须拒绝该取值。"""
    uid, cid = fixture_ids
    with pytest.raises(IntegrityError) as e:
        _insert_coupon(db, cid, uid, 1, "EXPIREDST1", status="EXPIRED")
    assert _violates(e.value, "ck_user_coupons_status")


# ---------- 留痕与风控约束 ----------

def test_degraded_without_reason_rejected(db):
    """降级必须给出原因，否则留痕无法用于排查（FR-053）。"""
    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO ai_invocations(purpose, model_id, prompt_version, input_features,"
                " latency_ms, degraded) VALUES ('RISK', 'm', 'v1', '{}', 10, true)"
            )
        )
    assert _violates(e.value, "ck_ai_invocations_degrade_reason")


def test_risk_score_out_of_range_rejected(db, fixture_ids):
    uid, _ = fixture_ids
    with pytest.raises(IntegrityError) as e:
        db.execute(
            text(
                "INSERT INTO risk_events(user_id, window_request_count, risk_score, decision,"
                " decided_by) VALUES (:uid, 5, 150, 'BLOCK', 'AI')"
            ),
            {"uid": uid},
        )
    assert _violates(e.value, "ck_risk_events_score_range")


# ---------- NFR-005：时区 ----------

def test_all_timestamp_columns_are_timestamptz(db):
    bad = db.execute(
        text(
            "SELECT table_name || '.' || column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND data_type LIKE 'timestamp%'"
            " AND data_type <> 'timestamp with time zone'"
        )
    ).scalars().all()
    assert bad == [], f"存在非 timestamptz 的时间列: {bad}"
