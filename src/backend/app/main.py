"""应用入口。

设计依据：api-specification.md（错误响应格式、health 语义）、
system-architecture.md 第六节（启动序列：迁移 → seed → 服务）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import engine
from .routers import auth, campaigns, coupons, recommendations, redemptions, risk, stats

log = logging.getLogger("coupon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动序列：seed 幂等执行。

    迁移由容器入口脚本或开发者显式执行 `alembic upgrade head`，不放在此处：
    多 worker 启动时并发跑迁移会互相争锁。
    """
    settings = get_settings()
    try:
        from .seed import run_seed

        result = run_seed()
        log.info("seed 完成: %s", result)
    except Exception as exc:  # 数据库未就绪时不阻断启动
        log.warning("seed 跳过（数据库可能未就绪）: %s", type(exc).__name__)
    if not settings.ai_configured:
        # 缺凭证不是错误：AI 功能降级，核心业务不受影响（FR-071 AC-2）
        log.warning("未配置 AWS_BEARER_TOKEN_BEDROCK，AI 功能进入降级模式")
    else:
        # 预热 Bedrock 客户端：构造客户端需加载服务模型并建立 TLS 连接，实测超过 1 秒。
        # 不预热则首个落入风控灰区的请求会因此撞满 2 秒预算而降级。
        from .services.bedrock import warm_up

        log.info("Bedrock 客户端预热: %s", "成功" if warm_up() else "失败")
    yield


app = FastAPI(
    title="优惠券发放与核销中心",
    description=(
        "SRC-G AI-DLC Workshop 项目。本页可直接调用接口用于演示。"
        " 角色：OPERATOR 运营 / USER 普通用户 / VERIFIER 核销员 / ADMIN 管理员。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# 前端与后端在 compose 中分属不同端口，开发期也需跨域。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """统一错误响应为 {code, message}。

    前端按 code 而非 message 分支（frontend-design.md 第五节），
    因此 code 是契约，message 可调整。
    """
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = detail
    else:
        body = {"code": "ERROR", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": "请求参数不合法",
            "details": [
                {"field": ".".join(str(x) for x in e["loc"][1:]), "msg": e["msg"]}
                for e in exc.errors()
            ],
        },
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
    return {"status": "ok", "database": database, "ai_configured": settings.ai_configured}


app.include_router(auth.router)
app.include_router(campaigns.router)
app.include_router(coupons.router)
app.include_router(redemptions.router)
app.include_router(recommendations.router)
app.include_router(risk.router)
app.include_router(stats.router)
