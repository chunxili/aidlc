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

# 各角色的具名账号。用常规姓名而非"运营小李""用户A"这类占位名：
# 界面会直接展示 display_name，占位名会让成品看起来像未完成的样例数据。
NAMED_USERS: list[tuple[str, str, str]] = [
    ("op001", "李彦", "OPERATOR"),
    ("verifier001", "王磊", "VERIFIER"),
    ("admin001", "张岚", "ADMIN"),
    ("user_a", "陈嘉", "USER"),
    ("user_b", "周宁", "USER"),
    ("user_c", "孙涛", "USER"),
]

# display_name 用 DO UPDATE 而非 DO NOTHING：既保持幂等，又能在改动展示名后
# 让已存在的账号同步更新，避免库里残留旧的占位名。
_INSERT = text(
    "INSERT INTO users(username, display_name, role)"
    " VALUES (:username, :display_name, :role)"
    " ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name"
)


def seed_users(db: Session, normal_user_count: int | None = None) -> dict[str, int]:
    """写入具名账号与批量普通用户，返回各自新增数量。"""
    if normal_user_count is None:
        normal_user_count = get_settings().seed_normal_user_count

    named_before = db.execute(text("SELECT count(*) FROM users")).scalar_one()

    for username, display_name, role in NAMED_USERS:
        db.execute(_INSERT, {"username": username, "display_name": display_name, "role": role})

    batch = [
        {"username": f"user{i:03d}", "display_name": f"会员{i:03d}", "role": "USER"}
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
