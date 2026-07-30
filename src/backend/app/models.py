"""ORM 模型。

设计依据：database-design.md 第二节。三条不变量由数据库约束强制，不靠应用层自觉：
- INV-1 库存守恒：campaigns 表级 CHECK (claimed_count <= total_stock)
- INV-2 券的完全划分：status 两态 + expires_at 惰性比较，不存 is_expired
- INV-3 状态两态：CHECK status IN ('UNUSED','USED')

限领的并发保障是 UNIQUE(campaign_id, user_id, seq)（ADR-001），不是应用层判断。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# ---- 枚举取值（用 CHECK 约束而非独立表，见 database-design.md users 一节）----
ROLES = ("OPERATOR", "USER", "VERIFIER", "ADMIN")
CATEGORIES = ("FOOD", "TRAVEL", "SHOPPING", "LIFE")
COUPON_STATUSES = ("UNUSED", "USED")
# 账号状态（ADR-012）：PENDING 可登录但不可办业务，REJECTED 不可登录
USER_STATUSES = ("ACTIVE", "PENDING", "REJECTED")
# 券型（ADR-013）：CASH 满减，DISCOUNT 折扣
COUPON_TYPES = ("CASH", "DISCOUNT")
RISK_DECISIONS = ("PASS", "BLOCK", "MANUAL_REVIEW")
RISK_DECIDED_BY = ("RULE", "AI")
RISK_STATUSES = ("PENDING", "RELEASED", "KEPT")
AI_PURPOSES = ("RECOMMEND", "RISK")


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Store(Base):
    """门店主数据（ADR-015）。本期只读，由 seed 写入广州各区门店。"""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    district: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_stores_district", "district"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 口令杂凑（ADR-011）：scrypt + 每用户随机盐，格式 scrypt$n$r$p$salt_hex$hash_hex。
    # 参数内嵌于串中，日后调参时旧杂凑仍可校验。禁止明文与无盐快速杂凑。
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 账号状态（ADR-012）。核销员与运营注册后为 PENDING，待管理员审核。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 仅核销员关联门店，由 CHECK 强制
    store_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stores.id"), nullable=True)
    # 审核留痕
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # risk_blocked 是 risk_events 的派生便利字段，供领券路径单次快速判断，
    # 避免每次领券都聚合 risk_events。一致性由 services/risk 在同一事务内维护。
    risk_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="ck_users_role"),
        CheckConstraint(_in("status", USER_STATUSES), name="ck_users_status"),
        # 门店归属只对核销员有意义：非核销员不得挂门店，核销员必须挂门店。
        # 用约束表达而非靠应用层自觉，避免出现"没有门店的核销员"这种无法核销归集的数据。
        CheckConstraint(
            "(role = 'VERIFIER' AND store_id IS NOT NULL)"
            " OR (role <> 'VERIFIER' AND store_id IS NULL)",
            name="ck_users_store_only_for_verifier",
        ),
        Index("ix_users_status_role", "status", "role"),
        Index("ix_users_store", "store_id"),
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # category 是 AI 生成推荐理由的语义来源（D-07）。缺了它，活动属性只有数字与时间，
    # AI 写不出有实质意义的理由。
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # 券型（ADR-013）：CASH 满减券，DISCOUNT 折扣券
    coupon_type: Mapped[str] = mapped_column(String(16), nullable=False, default="CASH", server_default="CASH")
    # CASH 券的减免额；DISCOUNT 券置空
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # 两种券型共用的最低消费门槛，0 表示无门槛
    min_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default="0"
    )
    # DISCOUNT 券：折后百分比（85 表示 8.5 折）与优惠封顶额，两者均必填
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    # 单调递增，永不回退（INV-1）。无作废功能，故不存在减少的场景。
    claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 领取后有效时长，分钟。分钟粒度使"过期券核销"可现场自然演示（ADR-003）。
    validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    per_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 不存 status（由 start_at/end_at 与 now() 派生，ADR-002）
    # 不存 remaining_stock（= total_stock - claimed_count，恒等式）

    __table_args__ = (
        CheckConstraint(_in("category", CATEGORIES), name="ck_campaigns_category"),
        CheckConstraint(_in("coupon_type", COUPON_TYPES), name="ck_campaigns_coupon_type"),
        # 按券型必填，由数据库强制而非应用层判断（ADR-013）
        CheckConstraint(
            "coupon_type <> 'CASH' OR (face_value IS NOT NULL AND face_value > 0)",
            name="ck_campaigns_cash_requires_face_value",
        ),
        CheckConstraint(
            "coupon_type <> 'DISCOUNT' OR (discount_percent IS NOT NULL"
            " AND discount_percent BETWEEN 1 AND 99"
            " AND max_discount_amount IS NOT NULL AND max_discount_amount > 0)",
            name="ck_campaigns_discount_requires_percent_and_cap",
        ),
        CheckConstraint("min_order_amount >= 0", name="ck_campaigns_min_order_non_negative"),
        CheckConstraint("total_stock > 0", name="ck_campaigns_total_stock_positive"),
        CheckConstraint("claimed_count >= 0", name="ck_campaigns_claimed_count_non_negative"),
        CheckConstraint("validity_minutes >= 1", name="ck_campaigns_validity_minutes_min"),
        CheckConstraint("per_user_limit >= 1", name="ck_campaigns_per_user_limit_min"),
        CheckConstraint("end_at > start_at", name="ck_campaigns_time_window"),
        # INV-1 的数据库级兜底：即使应用层写错，超发也会被数据库直接拒绝。
        CheckConstraint("claimed_count <= total_stock", name="ck_campaigns_no_oversell"),
        Index("ix_campaigns_window", "start_at", "end_at"),
        Index("ix_campaigns_category", "category"),
    )


class UserCoupon(Base):
    __tablename__ = "user_coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    # 该用户在本活动的第几张。与 campaign_id/user_id 构成唯一键，是限领的并发保障。
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # 10 位 Crockford Base32，不可预测（ADR-010）。核销仅凭券码，故不可预测是安全前提。
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="UNUSED", server_default="UNUSED")
    claimed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # min(campaign.end_at, claimed_at + validity_minutes)，领取时计算并落库（ADR-003）。
    # 注意区分：expires_at 是落库数据；"是否已过期"是对它的实时比较，永不落库。
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    # 核销门店，使管理员可按门店归集核销数据（ADR-014）
    used_store_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stores.id"), nullable=True)
    # 核销时的事实快照：不可由活动现值重算，因为活动配置可能已被修改
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        # 限领的并发保障（ADR-001）：并发下两个请求算出同一个 seq，数据库拒绝其中一个，
        # 触发回滚，campaign.claimed_count 的 +1 随之撤销，无需任何补偿逻辑。
        UniqueConstraint("campaign_id", "user_id", "seq", name="uq_user_coupons_campaign_user_seq"),
        CheckConstraint(_in("status", COUPON_STATUSES), name="ck_user_coupons_status"),
        CheckConstraint("seq >= 1", name="ck_user_coupons_seq_min"),
        # 使核销三字段无法出现不一致状态。
        CheckConstraint(
            "(status = 'USED' AND used_at IS NOT NULL AND used_by IS NOT NULL)"
            " OR (status = 'UNUSED' AND used_at IS NULL AND used_by IS NULL)",
            name="ck_user_coupons_used_consistency",
        ),
        Index("ix_user_coupons_campaign_status", "campaign_id", "status"),
        Index("ix_user_coupons_user_claimed_at", "user_id", "claimed_at"),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("campaigns.id"), nullable=True)
    window_request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 规则层直接拦截时可为空（未调用 AI）。
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(8), nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # 追溯 AI 判定理由。运营看不到理由就无从审核标记（NFR-008、FR-052 AC-2）。
    ai_invocation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_invocations.id"), nullable=True
    )
    # 规则层拦截时填规则说明文本，保证 ai_reason 永不为空。
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    handled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("decision", RISK_DECISIONS), name="ck_risk_events_decision"),
        CheckConstraint(_in("decided_by", RISK_DECIDED_BY), name="ck_risk_events_decided_by"),
        CheckConstraint(_in("status", RISK_STATUSES), name="ck_risk_events_status"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_risk_events_score_range",
        ),
        Index("ix_risk_events_created_at", "created_at"),
        Index("ix_risk_events_status", "status"),
        Index("ix_risk_events_user_created", "user_id", "created_at"),
    )


class AiInvocation(Base):
    __tablename__ = "ai_invocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    # 输入特征快照。不存完整 prompt：由 prompt_version + 快照可完整重建，
    # 同时避免表膨胀与凭证混入风险（NFR-004）。
    input_features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    degrade_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("purpose", AI_PURPOSES), name="ck_ai_invocations_purpose"),
        # degraded 为真时必须给出原因，否则留痕无法用于排查。
        CheckConstraint(
            "degraded = false OR degrade_reason IS NOT NULL",
            name="ck_ai_invocations_degrade_reason",
        ),
        Index("ix_ai_invocations_purpose_created", "purpose", "created_at"),
    )
