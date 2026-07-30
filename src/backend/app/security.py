"""JWT 认证与角色授权。

设计依据：api-specification.md 第十节「路由与角色映射强制表」。
授权由**单一依赖工厂** require_roles 实现，角色判断不散落在处理函数内部：
那张表是唯一事实来源，散落即意味着表与实现会漂移（FR-061）。
"""

from __future__ import annotations

import datetime as dt

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

# auto_error=False：缺失 token 时由本模块统一抛 401，保证响应体格式一致。
_bearer = HTTPBearer(auto_error=False)


def create_access_token(user: User) -> str:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _unauthenticated() -> HTTPException:
    # 不区分"无 token""已过期""签名无效"：区分会给攻击者可用信息。
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHENTICATED", "message": "未认证或凭证已失效"},
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise _unauthenticated()
    settings = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = int(payload["sub"])
    except Exception:
        raise _unauthenticated() from None

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise _unauthenticated()
    # 只拒 REJECTED：PENDING 必须能取到身份，否则无法查看自己的申请进度（ADR-012）
    if user.status == "REJECTED":
        raise _unauthenticated()
    return user


def require_roles(*roles: str):
    """返回一个依赖，只允许指定角色且账号已启用的用户通过。

    "能否登录"与"能否办业务"是两层（ADR-012）：待审核账号可以登录看进度，
    但不得访问任何业务接口，且返回专用错误码供前端跳转到审核进度页 ——
    否则用户会遇到"登录成功却处处 403 且没有解释"。

    越权时响应体只含 code 与 message，**不泄露目标资源是否存在**（SC-008）。
    """

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.status == "PENDING":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_PENDING_APPROVAL",
                    "message": "账号正在审核中，通过后即可使用",
                },
            )
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "无权访问该资源"},
            )
        return user

    return _dep


# 便捷别名，与 api-specification.md 第十节的映射表一一对应。
require_operator = require_roles("OPERATOR")
require_user = require_roles("USER")
require_verifier = require_roles("VERIFIER")
require_admin = require_roles("ADMIN")
require_admin_or_operator = require_roles("ADMIN", "OPERATOR")
