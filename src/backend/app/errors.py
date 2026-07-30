"""业务异常与错误码。

错误码取自 api-specification.md 第一节。code 是契约，message 可调整
（前端按 code 分支，frontend-design.md 第五节）。
"""

from __future__ import annotations

from fastapi import HTTPException


class BusinessError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


# ---- 404 ----
def campaign_not_found() -> BusinessError:
    return BusinessError(404, "CAMPAIGN_NOT_FOUND", "活动不存在")


def coupon_not_found() -> BusinessError:
    return BusinessError(404, "COUPON_NOT_FOUND", "券不存在")


def risk_event_not_found() -> BusinessError:
    return BusinessError(404, "RISK_EVENT_NOT_FOUND", "风险标记不存在")


# ---- 409 业务状态冲突 ----
def out_of_stock() -> BusinessError:
    return BusinessError(409, "OUT_OF_STOCK", "库存不足")


def per_user_limit_reached() -> BusinessError:
    return BusinessError(409, "PER_USER_LIMIT_REACHED", "已达领取上限")


def campaign_not_active() -> BusinessError:
    return BusinessError(409, "CAMPAIGN_NOT_ACTIVE", "活动未开始或已结束")


def coupon_already_used() -> BusinessError:
    return BusinessError(409, "COUPON_ALREADY_USED", "已核销")


def coupon_expired() -> BusinessError:
    return BusinessError(409, "COUPON_EXPIRED", "券已过期")


def stock_cannot_decrease() -> BusinessError:
    return BusinessError(
        409,
        "STOCK_CANNOT_DECREASE",
        "库存只能调高：调低会使已领取数超过总库存，破坏库存守恒",
    )


def field_immutable(field: str, why: str) -> BusinessError:
    return BusinessError(409, "FIELD_IMMUTABLE", f"{field} 不可修改：{why}")


# ---- 403 风控（与越权同为 403，但 code 不同，文案也不同）----
def risk_blocked() -> BusinessError:
    return BusinessError(403, "RISK_BLOCKED", "操作过于频繁，已被风控拦截")


def risk_manual_review() -> BusinessError:
    return BusinessError(
        403, "RISK_MANUAL_REVIEW", "账号存在异常，需人工审核，审核通过后请重新领取"
    )


def code_generation_failed() -> BusinessError:
    # 不得静默降级为可预测券码（ADR-010 是安全约束）
    return BusinessError(500, "INTERNAL_ERROR", "券码生成失败，请重试")
