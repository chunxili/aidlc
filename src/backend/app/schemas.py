"""请求与响应模型。契约以 api-specification.md 为准。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["FOOD", "TRAVEL", "SHOPPING", "LIFE"]
CampaignStatus = Literal["PENDING", "ACTIVE", "ENDED"]
CouponType = Literal["CASH", "DISCOUNT"]
RegisterRole = Literal["USER", "VERIFIER", "OPERATOR"]


# ---------- 门店 ----------

class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    district: str
    address: str


# ---------- 认证与注册 ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str
    status: str
    phone: str | None = None
    store_id: int | None = None
    store_name: str | None = None
    reject_reason: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=4, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role: RegisterRole
    phone: str | None = Field(default=None, max_length=20)
    # 仅核销人员需要，其余角色传入将被拒绝
    store_id: int | None = None


class RegisterOut(BaseModel):
    user: UserOut
    # 核销员与运营注册后需管理员审核，前端据此决定跳转到进度页还是直接登录
    needs_approval: bool


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 管理员审核与名册 ----------

class PendingUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    phone: str | None
    store_id: int | None
    store_name: str | None
    store_district: str | None
    created_at: dt.datetime


class ReviewIn(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=256)


class VerifierOut(BaseModel):
    id: int
    username: str
    display_name: str
    phone: str | None
    status: str
    store_id: int
    store_code: str
    store_name: str
    store_district: str
    redeemed_count: int
    created_at: dt.datetime


# ---------- 管理员人员名册与下钻（CR-002）----------

class OperatorOut(BaseModel):
    """运营人员名册行（FR-069）。列的是投放业绩，不是账号资料。"""

    id: int
    username: str
    display_name: str
    phone: str | None
    status: str
    campaign_count: int
    total_stock: int
    claimed_count: int
    used_count: int
    # 分母为 0 时为 None 而非 0：「无人领取」与「领了没人用」是两回事，
    # 用 0 表示前者会误导运营复盘。口径与 CampaignStatsOut.redeem_rate 一致。
    redeem_rate: float | None
    created_at: dt.datetime


class VerifierBrief(BaseModel):
    id: int
    username: str
    display_name: str
    phone: str | None
    store_name: str
    store_district: str


class RedemptionRecordOut(BaseModel):
    """核销记录行（FR-070）。金额取核销时落库的快照，不用活动现值重算（ADR-017）。"""

    id: int
    code: str
    campaign_name: str
    coupon_type: str
    benefit_text: str
    order_amount: Decimal | None
    discount_amount: Decimal | None
    # order_amount - discount_amount，派生不落库
    payable_amount: Decimal | None
    used_at: dt.datetime
    store_name: str | None


class VerifierRedemptionsOut(BaseModel):
    verifier: VerifierBrief
    items: list[RedemptionRecordOut]
    total: int
    page: int
    page_size: int


class OperatorBrief(BaseModel):
    id: int
    username: str
    display_name: str
    phone: str | None
    status: str


class OperatorCampaignOut(BaseModel):
    """运营发布的活动行（FR-071）。界面称「发布的券」，数据粒度是活动（Q-023）。"""

    id: int
    name: str
    category: str
    coupon_type: str
    benefit_text: str
    total_stock: int
    claimed_count: int
    used_count: int
    remaining_stock: int
    status: str
    start_at: dt.datetime
    end_at: dt.datetime


class OperatorCampaignsOut(BaseModel):
    operator: OperatorBrief
    items: list[OperatorCampaignOut]
    total: int
    page: int
    page_size: int


# ---------- 活动 ----------

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: Category
    coupon_type: CouponType = "CASH"
    # CASH 券必填；DISCOUNT 券须留空
    face_value: Decimal | None = Field(default=None, gt=0)
    # 两种券型共用的最低消费门槛，0 表示无门槛
    min_order_amount: Decimal = Field(default=Decimal(0), ge=0)
    # DISCOUNT 券必填：折后百分比（85 = 8.5 折）与优惠封顶
    discount_percent: int | None = Field(default=None, ge=1, le=99)
    max_discount_amount: Decimal | None = Field(default=None, gt=0)
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
    coupon_type: CouponType
    face_value: Decimal | None
    min_order_amount: Decimal
    discount_percent: int | None
    max_discount_amount: Decimal | None
    # 由后端统一生成的优惠描述，前端直接展示，避免两端各拼一套文案
    benefit_text: str
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
    coupon_type: CouponType
    face_value: Decimal | None
    min_order_amount: Decimal
    discount_percent: int | None
    max_discount_amount: Decimal | None
    benefit_text: str
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
    coupon_type: CouponType
    face_value: Decimal | None
    min_order_amount: Decimal
    benefit_text: str
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
    # 引入券型后必填：没有订单金额既无法判断门槛，也无法算折扣券的优惠额（ADR-014）
    order_amount: Decimal = Field(gt=0)


class RedeemOut(BaseModel):
    code: str
    benefit_text: str
    order_amount: Decimal
    discount_amount: Decimal
    payable_amount: Decimal
    used_at: dt.datetime
    used_by: str
    store_name: str | None


class RedeemCheckOut(BaseModel):
    code: str
    campaign_name: str
    coupon_type: CouponType
    benefit_text: str
    face_value: Decimal | None
    min_order_amount: Decimal
    discount_percent: int | None
    max_discount_amount: Decimal | None
    display_status: str
    owner: str
    redeemable: bool
    reason: str | None


# ---------- 推荐 ----------

class RecommendationItem(BaseModel):
    campaign_id: int
    campaign_name: str
    category: Category
    coupon_type: CouponType
    face_value: Decimal | None
    benefit_text: str
    remaining_stock: int
    reason: str


class RecommendationOut(BaseModel):
    items: list[RecommendationItem]
    degraded: bool
    degrade_reason: str | None
    cold_start: bool
    # AI 对用户需求的理解概述。仅"按需求找券"接口填充；自动推荐接口为 None。
    # 默认 None 保证旧接口契约向后兼容。
    analysis: str | None = None


class NeedRecommendationIn(BaseModel):
    """用户用一句话描述的需求，由 AI 理解后从全部可领券中匹配（FR-040 扩展）。"""

    need: str = Field(..., min_length=1, max_length=200)


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
