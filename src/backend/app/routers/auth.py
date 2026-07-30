"""认证与注册路由（FR-060 已废弃，改为 FR-063 ~ FR-065）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Store, User
from ..schemas import LoginIn, LoginOut, RegisterIn, RegisterOut, UserOut
from ..security import create_access_token, get_current_user
from ..services import account as svc

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _user_out(db: Session, user: User) -> UserOut:
    store = db.get(Store, user.store_id) if user.store_id else None
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        phone=user.phone,
        store_id=user.store_id,
        store_name=store.name if store else None,
        reject_reason=user.reject_reason,
    )


@router.post("/register", response_model=RegisterOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> RegisterOut:
    """自助注册。

    会员即时启用；核销人员（须选门店）与运营人员待管理员审核。
    """
    user = svc.register(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
        phone=payload.phone,
        store_id=payload.store_id,
    )
    return RegisterOut(user=_user_out(db, user), needs_approval=user.status == "PENDING")


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    user = svc.authenticate(db, payload.username, payload.password)
    return LoginOut(access_token=create_access_token(user), user=_user_out(db, user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    """供前端刷新后恢复登录态。待审核账号也能调用，用于查看申请进度。"""
    return _user_out(db, user)
