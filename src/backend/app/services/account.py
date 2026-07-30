"""注册、登录与审核（FR-063 ~ FR-067）。

审核规则（CR-001）：
- 会员（USER）注册即时启用
- 核销员（VERIFIER）须选择门店，注册后待管理员审核
- 运营（OPERATOR）注册后待管理员审核
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BusinessError
from ..models import Store, User
from ..passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password

SELF_REGISTRABLE_ROLES = ("USER", "VERIFIER", "OPERATOR")
# 注册即启用的角色。其余角色需管理员审核。
AUTO_ACTIVE_ROLES = ("USER",)


def _invalid(message: str) -> BusinessError:
    return BusinessError(400, "VALIDATION_ERROR", message)


def register(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str,
    phone: str | None = None,
    store_id: int | None = None,
) -> User:
    username = username.strip()
    display_name = display_name.strip()

    if role not in SELF_REGISTRABLE_ROLES:
        # 管理员不可自助注册：谁来审核管理员？这是自举问题，由初始化解决。
        raise _invalid("该角色不支持自助注册")
    if len(username) < 4:
        raise _invalid("账号至少 4 个字符")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise _invalid(f"密码至少 {MIN_PASSWORD_LENGTH} 个字符")
    if not display_name:
        raise _invalid("请填写姓名")

    if role == "VERIFIER":
        if store_id is None:
            raise _invalid("核销人员必须选择所属门店")
        if db.get(Store, store_id) is None:
            raise _invalid("所选门店不存在")
    elif store_id is not None:
        # 门店归属只对核销员有意义，数据库亦有 CHECK 兜底
        raise _invalid("该角色无需选择门店")

    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        # 被驳回的申请允许用同一账号重新提交：更新原记录而非新建，
        # 否则用户只能换账号名反复注册，留下一堆无效记录（Q-018）。
        if existing.status != "REJECTED":
            raise BusinessError(409, "USERNAME_TAKEN", "该账号已被使用")
        existing.display_name = display_name
        existing.password_hash = hash_password(password)
        existing.role = role
        existing.phone = phone
        existing.store_id = store_id
        existing.status = "ACTIVE" if role in AUTO_ACTIVE_ROLES else "PENDING"
        existing.reviewed_by = None
        existing.reviewed_at = None
        existing.reject_reason = None
        db.commit()
        db.refresh(existing)
        return existing

    user = User(
        username=username,
        display_name=display_name,
        role=role,
        password_hash=hash_password(password),
        status="ACTIVE" if role in AUTO_ACTIVE_ROLES else "PENDING",
        phone=phone,
        store_id=store_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> User:
    """校验账号口令。

    账号不存在与口令错误返回**同一个** 401：区分二者会把"哪些账号存在"
    泄露给探测者。
    """
    user = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise BusinessError(401, "UNAUTHENTICATED", "账号或密码有误")
    if user.status == "REJECTED":
        raise BusinessError(
            403,
            "ACCOUNT_REJECTED",
            f"申请未通过：{user.reject_reason or '未说明原因'}。可修改资料后重新提交",
        )
    return user


# ---------- 管理员审核（FR-066）----------

def list_pending(db: Session) -> list[tuple[User, Store | None]]:
    rows = db.execute(
        select(User, Store)
        .outerjoin(Store, Store.id == User.store_id)
        .where(User.status == "PENDING")
        .order_by(User.created_at)
    ).all()
    return [(r[0], r[1]) for r in rows]


def review(db: Session, user_id: int, approve: bool, reviewer: User, reason: str | None) -> User:
    """审批注册申请。幂等：重复审批返回当前状态。"""
    target = db.get(User, user_id)
    if target is None:
        raise BusinessError(404, "USER_NOT_FOUND", "申请不存在")
    if target.status != "PENDING":
        return target

    target.status = "ACTIVE" if approve else "REJECTED"
    target.reviewed_by = reviewer.id
    target.reviewed_at = dt.datetime.now(dt.UTC)
    target.reject_reason = None if approve else (reason or "资料不符合要求")
    db.commit()
    db.refresh(target)
    return target


def list_verifiers(
    db: Session, district: str | None = None, store_id: int | None = None
) -> list[tuple[User, Store, int]]:
    """全门店核销人员名册（FR-067），附各人的累计核销数。"""
    from ..models import UserCoupon

    used = (
        select(UserCoupon.used_by, func.count(UserCoupon.id).label("cnt"))
        .where(UserCoupon.status == "USED")
        .group_by(UserCoupon.used_by)
        .subquery()
    )
    stmt = (
        select(User, Store, func.coalesce(used.c.cnt, 0))
        .join(Store, Store.id == User.store_id)
        .outerjoin(used, used.c.used_by == User.id)
        .where(User.role == "VERIFIER")
        .order_by(Store.district, Store.code, User.created_at)
    )
    if district:
        stmt = stmt.where(Store.district == district)
    if store_id:
        stmt = stmt.where(Store.id == store_id)
    return [(r[0], r[1], r[2]) for r in db.execute(stmt).all()]
