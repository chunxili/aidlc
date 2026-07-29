"""数据库引擎、会话与声明基类。

设计依据：technology-stack.md 第一节（SQLAlchemy 2.0 + psycopg v3，同步）。
选同步而非异步的理由见 technology-stack.md「替代方案」：领券路径的瓶颈是单行热点的
行锁，由数据库决定，异步换不到收益。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """全部 ORM 模型的声明基类，Alembic 以其 metadata 生成迁移。"""


_settings = get_settings()

# pool_pre_ping：compose 下容器启动顺序不确定，避免取到已失效的连接。
# connect_timeout：数据库不可达时快速失败。缺少该参数时握手会在 IPv6/IPv4 双栈上
# 各自等待系统默认超时，实测 /api/health 需 6 秒以上才返回，健康检查失去意义。
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={"connect_timeout": 3},
)

# expire_on_commit=False：提交后仍可读取对象属性，避免为构造响应而额外查询。
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
