"""应用入口。

T-01 阶段仅提供 /api/health。业务路由在后续任务中逐个挂载。

设计依据：api-specification.md 第九节（health 端点语义）、
system-architecture.md 第六节（部署与启动序列）。
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from .config import get_settings
from .db import engine

app = FastAPI(
    title="优惠券发放与核销中心",
    description="SRC-G AI-DLC Workshop 项目。接口文档可直接用于演示调用。",
    version="0.1.0",
)


@app.get("/api/health", tags=["运维"])
def health() -> dict[str, str | bool]:
    """健康检查。

    ai_configured=false 表示未注入 Bedrock 凭证，AI 功能处于降级模式。
    该状态**不影响** status: ok —— 缺凭证时服务必须可用（FR-071 AC-2）。
    """
    settings = get_settings()

    database = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        # 不回传异常细节：可能含连接串与口令（NFR-004）。
        database = "unavailable"

    return {
        "status": "ok",
        "database": database,
        "ai_configured": settings.ai_configured,
    }
