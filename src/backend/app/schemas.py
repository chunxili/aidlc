"""请求与响应模型。契约以 api-specification.md 为准。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["FOOD", "TRAVEL", "SHOPPING", "LIFE"]
CampaignStatus = Literal["PENDING", "ACTIVE", "ENDED"]


# ---------- 认证 ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str


class LoginIn(BaseModel):
    username: str
    # 需求 4.7 允许使用 Mock 用户，本项目不实现密码体系，故此字段**不做校验**。
    # 保留它是为了让登录界面具备常规形态；界面上明示"当前环境未启用密码校验"，
    # 不制造"已校验"的错觉。
    password: str | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 活动 ----------

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: Category
    face_value: Decimal = Field(gt=0)
    total_stock: int = Field(ge=1)
    start_at: dt.datetime
    end_at: dt.datetime
    # 分钟粒度使"过期券核销"可现场自然演示（ADR-003）
    validity_minutes: int = Field(ge=1)
    per_user_limit: int = Field(default=1, ge=1)


class CampaignUpdate(BaseModel):
    """只列可变字段。face_value / validity_minutes / 已开始活动的 start_at 不可改。

    不可变字段若出现在请求体中，由 extra="forbid" 直接拒绝，
    使"不可变"在契约层就成立，而不是靠处理函数逐个判断。
    """

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    category: Category | None = None
    end_at: dt.datetime | None = None
    per_user_limit: int | None = Field(default=None, ge=1)
    total_stock: int | None = Field(default=None, ge=1)


class CampaignOut(BaseModel):
    id: int
    name: str
    category: Category
    face_value: Decimal
    total_stock: int
    claimed_count: int
    remaining_stock: int
    status: CampaignStatus
    start_at: dt.datetime
    end_at: dt.datetime
    validity_minutes: int
    per_user_limit: int


class AvailableCampaignOut(BaseModel):
    """USER 视图：不下发统计与风控字段（最小权限）。"""

    id: int
    name: str
    category: Category
    face_value: Decimal
    remaining_stock: int
    end_at: dt.datetime
    validity_minutes: int
    per_user_limit: int
    my_claimed_count: int


# ---------- 券 ----------

class CouponOut(BaseModel):
    id: int
    code: str
    campaign_id: int
    campaign_name: str
    face_value: Decimal
    status: str
    display_status: str
    seq: int
    claimed_at: dt.datetime
    expires_at: dt.datetime


class RiskOut(BaseModel):
    score: int | None
    decision: str
    decided_by: str
    degraded: bool
    reason: str | None = None


class ClaimIn(BaseModel):
    campaign_id: int


class ClaimOut(BaseModel):
    coupon: CouponOut
    risk: RiskOut


class Paged(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


# ---------- 核销 ----------

class RedeemIn(BaseModel):
    code: str


class RedeemOut(BaseModel):
    code: str
    face_value: Decimal
    used_at: dt.datetime
    used_by: str


class RedeemCheckOut(BaseModel):
    code: str
    campaign_name: str
    face_value: Decimal
    display_status: str
    owner: str
    redeemable: bool
    reason: str | None


# ---------- 推荐 ----------

class RecommendationItem(BaseModel):
    campaign_id: int
    campaign_name: str
    category: Category
    face_value: Decimal
    remaining_stock: int
    reason: str


class RecommendationOut(BaseModel):
    items: list[RecommendationItem]
    degraded: bool
    degrade_reason: str | None
    cold_start: bool


# ---------- 风控 ----------

class RiskEventOut(BaseModel):
    id: int
    user_id: int
    username: str
    campaign_id: int | None
    window_request_count: int
    risk_score: int | None
    decision: str
    decided_by: str
    degraded: bool
    # 必需字段而非附加信息：运营看不到理由就无从审核（FR-052 AC-2）
    ai_reason: str
    status: str
    handled_by: str | None
    handled_at: dt.datetime | None
    created_at: dt.datetime


class RiskHandleIn(BaseModel):
    action: Literal["RELEASE", "KEEP"]


# ---------- 统计 ----------

class CampaignStatsOut(BaseModel):
    campaign_id: int
    campaign_name: str
    total_stock: int
    claimed_count: int
    remaining_stock: int
    used_count: int
    active_count: int
    expired_count: int
    claim_rate: float
    redeem_rate: float | None
    # 口径说明由后端下发，前端直接展示，避免前后端口径漂移（FR-030 AC-4）
    claim_rate_basis: str
    redeem_rate_basis: str


class OverviewOut(BaseModel):
    campaign_count: int
    total_stock: int
    claimed_count: int
    used_count: int
    risk_blocked_24h: int
    risk_pending_count: int


class IntegrityOut(BaseModel):
    inv1_stock_overflow_count: int
    inv2_mismatch_campaign_ids: list[int]
    ok: bool
