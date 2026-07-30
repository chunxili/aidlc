"""Mock 用户初始化（FR-062）。

幂等：用 ON CONFLICT (username) DO NOTHING，重复启动不产生重复数据。
批量普通用户是硬需求而非便利：FR-010 AC-1 要求 N+1 个**不同**用户并发领取，
同一用户会被风控拦截，用手写的几个账号无法完成该验收。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal

# 演示流程用的具名账号（对应竞赛演示 a~f 的角色）
NAMED_USERS: list[tuple[str, str, str]] = [
    ("op001", "运营小李", "OPERATOR"),
    ("verifier001", "核销员小王", "VERIFIER"),
    ("admin001", "管理员小张", "ADMIN"),
    ("user_a", "用户A", "USER"),
    ("user_b", "用户B", "USER"),
    ("user_c", "用户C", "USER"),
]

_INSERT = text(
    "INSERT INTO users(username, display_name, role)"
    " VALUES (:username, :display_name, :role)"
    " ON CONFLICT (username) DO NOTHING"
)


def seed_users(db: Session, normal_user_count: int | None = None) -> dict[str, int]:
    """写入具名账号与批量普通用户，返回各自新增数量。"""
    if normal_user_count is None:
        normal_user_count = get_settings().seed_normal_user_count

    named_before = db.execute(text("SELECT count(*) FROM users")).scalar_one()

    for username, display_name, role in NAMED_USERS:
        db.execute(_INSERT, {"username": username, "display_name": display_name, "role": role})

    batch = [
        {"username": f"user{i:03d}", "display_name": f"压测用户{i:03d}", "role": "USER"}
        for i in range(1, normal_user_count + 1)
    ]
    if batch:
        db.execute(_INSERT, batch)

    db.commit()
    after = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    return {"before": named_before, "after": after, "inserted": after - named_before}


def run_seed() -> dict[str, int]:
    db = SessionLocal()
    try:
        return seed_users(db)
    finally:
        db.close()
