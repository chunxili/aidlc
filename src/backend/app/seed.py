"""基础与运营配置数据初始化（FR-062、FR-068、FR-072）。

账号与门店保持幂等更新；运营策略和设置只在尚未初始化时创建，绝不覆盖运营修改。
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal
from .passwords import hash_password
from .store_data import STORES

DEFAULT_PASSWORD = "Coupon@2026"

NAMED_USERS: list[tuple[str, str, str, str, str | None]] = [
    ("admin001", "张岚", "ADMIN", "13800000001", None),
    ("op001", "李彦", "OPERATOR", "13800000002", None),
    ("op002", "林薇", "OPERATOR", "13800000012", None),
    ("op003", "郭铭", "OPERATOR", "13800000013", None),
    ("verifier001", "王磊", "VERIFIER", "13800000003", "GZ-TH-001"),
    ("verifier002", "赵敏", "VERIFIER", "13800000004", "GZ-YX-001"),
    ("verifier003", "何俊", "VERIFIER", "13800000005", "GZ-PY-001"),
    ("verifier004", "曾丽", "VERIFIER", "13800000006", "GZ-TH-002"),
    ("verifier005", "邓超", "VERIFIER", "13800000007", "GZ-HZ-001"),
    ("verifier006", "梁悦", "VERIFIER", "13800000008", "GZ-LW-001"),
    ("user_a", "陈嘉", "USER", "13900000001", None),
    ("user_b", "周宁", "USER", "13900000002", None),
    ("user_c", "孙涛", "USER", "13900000003", None),
]

# 待管理员审核的注册申请（CR-002 / D-CR002-1）。
# 审核队列在演示时不能是空的：管理员后台的第一屏就是审核，空列表让人无从判断功能是否可用。
# 用具名中文申请人，而非验收脚本生成的 operator_82215d20「待审OPERATOR」这类占位数据。
PENDING_APPLICANTS: list[tuple[str, str, str, str, str | None]] = [
    ("verifier101", "许静", "VERIFIER", "13700000001", "GZ-BY-001"),
    ("verifier102", "冯凯", "VERIFIER", "13700000002", "GZ-HZ-002"),
    ("verifier103", "苏珊", "VERIFIER", "13700000003", "GZ-NS-001"),
    ("op101", "唐宇", "OPERATOR", "13700000011", None),
    ("op102", "钟晴", "OPERATOR", "13700000012", None),
]

DEFAULT_AUDIENCE_THRESHOLDS = {
    "new_user_days": 7,
    "active_days": 7,
    "dormant_days": 30,
    "redeem_sample_size": 3,
    "high_redeem_rate": 60,
    "low_redeem_rate": 20,
}

DEFAULT_ALERT_SETTINGS = {
    "quota_usage": {"enabled": True, "threshold": 0.8},
    "exhaustion_hours": {"enabled": True, "threshold": 2.0},
    "claim_growth": {"enabled": True, "threshold": 1.0},
    "risk_rate": {"enabled": True, "threshold": 0.1},
    "pending_risks": {"enabled": True, "threshold": 20.0},
    "redeem_rate_gap": {"enabled": True, "threshold": 0.2},
}

_FACTOR_WEIGHTS = {
    "frequency": 40,
    "new_account": 15,
    "low_redeem": 15,
    "unused_coupons": 10,
    "risk_history": 20,
    "high_value": 10,
}

DEFAULT_RISK_POLICIES = (
    ("低保护", "LOW", 15, 50, 80),
    ("中保护", "MEDIUM", 10, 40, 70),
    ("高保护", "HIGH", 7, 30, 60),
)

_UPSERT_STORE = text(
    "INSERT INTO stores(code, name, district, address)"
    " VALUES (:code, :name, :district, :address)"
    " ON CONFLICT (code) DO UPDATE"
    " SET name = EXCLUDED.name, district = EXCLUDED.district, address = EXCLUDED.address"
)

# display_name 与 password_hash 用 DO UPDATE 而非 DO NOTHING：既保持幂等，
# 又能在改动展示名或重置初始口令后让已存在的账号同步更新，
# 避免库里残留旧的占位名或空口令（空口令账号将无法登录）。
#
# status 刻意**不**进 DO UPDATE 的更新列：种子申请人一旦被管理员审批过，
# 重启服务不得把它拽回 PENDING —— 那会让演示中刚做完的审批凭空消失。
_UPSERT_USER = text(
    "INSERT INTO users(username, display_name, role, password_hash, status, phone, store_id)"
    " VALUES (:username, :display_name, :role, :password_hash, :status, :phone,"
    "         (SELECT id FROM stores WHERE code = :store_code))"
    " ON CONFLICT (username) DO UPDATE"
    " SET display_name = EXCLUDED.display_name,"
    "     password_hash = COALESCE(users.password_hash, EXCLUDED.password_hash),"
    "     phone = COALESCE(users.phone, EXCLUDED.phone),"
    "     store_id = EXCLUDED.store_id"
)

_INSERT_POLICY = text(
    "INSERT INTO risk_policies(name,level,is_global_default,hard_rules,factor_weights,"
    " review_threshold,block_threshold,created_by,updated_by)"
    " VALUES (:name,:level,false,CAST(:hard_rules AS jsonb),CAST(:factor_weights AS jsonb),"
    " :review_threshold,:block_threshold,:operator_id,:operator_id)"
    " ON CONFLICT (name) DO NOTHING"
)


def seed_stores(db: Session) -> int:
    for code, name, district, address in STORES:
        db.execute(
            _UPSERT_STORE, {"code": code, "name": name, "district": district, "address": address}
        )
    db.commit()
    return db.execute(text("SELECT count(*) FROM stores")).scalar_one()


def seed_users(db: Session, normal_user_count: int | None = None) -> dict[str, int]:
    if normal_user_count is None:
        normal_user_count = get_settings().seed_normal_user_count

    before = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    shared_hash = hash_password(DEFAULT_PASSWORD)

    for username, display_name, role, phone, store_code in NAMED_USERS:
        db.execute(
            _UPSERT_USER,
            {
                "username": username,
                "display_name": display_name,
                "role": role,
                "password_hash": shared_hash,
                "status": "ACTIVE",
                "phone": phone,
                "store_code": store_code,
            },
        )

    for username, display_name, role, phone, store_code in PENDING_APPLICANTS:
        db.execute(
            _UPSERT_USER,
            {
                "username": username,
                "display_name": display_name,
                "role": role,
                "password_hash": shared_hash,
                "status": "PENDING",
                "phone": phone,
                "store_code": store_code,
            },
        )

    batch = [
        {
            "username": f"user{i:03d}",
            "display_name": f"会员{i:03d}",
            "role": "USER",
            "password_hash": shared_hash,
            "status": "ACTIVE",
            "phone": None,
            "store_code": None,
        }
        for i in range(1, normal_user_count + 1)
    ]
    if batch:
        db.execute(_UPSERT_USER, batch)

    db.commit()
    after = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    return {"before": before, "after": after, "inserted": after - before}


def seed_operator_settings(db: Session) -> dict[str, int]:
    """仅首次创建默认策略与单例设置，后续启动绝不覆盖运营修改。"""
    existing = db.execute(text("SELECT count(*) FROM operator_settings WHERE id=1")).scalar_one()
    if existing:
        return {
            "risk_policies": db.execute(text("SELECT count(*) FROM risk_policies")).scalar_one(),
            "operator_settings": 1,
        }

    operator_id = db.execute(text("SELECT id FROM users WHERE username='op001'")).scalar_one()
    for name, level, hard_threshold, review_threshold, block_threshold in DEFAULT_RISK_POLICIES:
        db.execute(
            _INSERT_POLICY,
            {
                "name": name,
                "level": level,
                "hard_rules": json.dumps(
                    {"window_seconds": 10, "hard_threshold": hard_threshold},
                    ensure_ascii=False,
                ),
                "factor_weights": json.dumps(_FACTOR_WEIGHTS, ensure_ascii=False),
                "review_threshold": review_threshold,
                "block_threshold": block_threshold,
                "operator_id": operator_id,
            },
        )

    medium_id = db.execute(
        text("SELECT id FROM risk_policies WHERE level='MEDIUM' ORDER BY id LIMIT 1")
    ).scalar_one()
    db.execute(text("UPDATE risk_policies SET is_global_default=false WHERE is_global_default"))
    db.execute(
        text("UPDATE risk_policies SET is_global_default=true WHERE id=:id"), {"id": medium_id}
    )
    db.execute(
        text(
            "INSERT INTO operator_settings(id,audience_thresholds,default_risk_policy_id,"
            " alert_settings,version,updated_by)"
            " VALUES (1,CAST(:audience AS jsonb),:policy_id,CAST(:alerts AS jsonb),1,:operator_id)"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {
            "audience": json.dumps(DEFAULT_AUDIENCE_THRESHOLDS, ensure_ascii=False),
            "policy_id": medium_id,
            "alerts": json.dumps(DEFAULT_ALERT_SETTINGS, ensure_ascii=False),
            "operator_id": operator_id,
        },
    )
    db.commit()
    return {
        "risk_policies": db.execute(text("SELECT count(*) FROM risk_policies")).scalar_one(),
        "operator_settings": db.execute(text("SELECT count(*) FROM operator_settings")).scalar_one(),
    }


def run_seed() -> dict[str, int]:
    db = SessionLocal()
    try:
        stores = seed_stores(db)
        result = seed_users(db)
        result["stores"] = stores
        result.update(seed_operator_settings(db))
        return result
    finally:
        db.close()
