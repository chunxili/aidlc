"""基础数据初始化（FR-062、FR-068）。

幂等：全部用 ON CONFLICT，重复启动不产生重复数据。

批量会员账号不是便利设施而是硬需求：FR-010 AC-1 要求 N+1 个**不同**用户
并发领取，同一用户会被风控拦截，用手写的几个账号无法完成该验收。

**首个管理员由此写入**：管理员审核他人注册，而管理员自己无法通过注册产生，
这是自举问题，只能由初始化解决（design-plan CR-001 残余风险已记录）。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal
from .passwords import hash_password
from .store_data import STORES

# 所有初始账号的统一口令。仅用于本地与演示环境；上线前必须强制改密。
DEFAULT_PASSWORD = "Coupon@2026"

# 各角色的具名账号。用常规姓名而非"运营小李""用户A"这类占位名：
# 界面直接展示 display_name，占位名会让成品看起来像未完成的样例数据。
# (账号, 姓名, 角色, 手机号, 门店编码)
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
    # 所有初始账号共用同一口令杂凑，避免为 200 个账号各跑一次 scrypt（每次约 70ms）
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


def run_seed() -> dict[str, int]:
    db = SessionLocal()
    try:
        stores = seed_stores(db)  # 门店须先于用户：核销员账号引用门店编码
        result = seed_users(db)
        result["stores"] = stores
        return result
    finally:
        db.close()
