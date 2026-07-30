"""ORM 模型。

三条核心不变量由数据库约束强制；运营增强 v2 在此基础上增加投放配置、
风控策略、活动级限制与配置审计（CR-002）。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

ROLES = ("OPERATOR", "USER", "VERIFIER", "ADMIN")
CATEGORIES = ("FOOD", "TRAVEL", "SHOPPING", "LIFE")
COUPON_STATUSES = ("UNUSED", "USED")
USER_STATUSES = ("ACTIVE", "PENDING", "REJECTED")
COUPON_TYPES = ("CASH", "DISCOUNT")
RISK_DECISIONS = ("PASS", "BLOCK", "MANUAL_REVIEW")
RISK_DECIDED_BY = ("RULE", "AI")
RISK_STATUSES = ("PENDING", "RELEASED", "KEPT")  # v1 兼容列
AI_PURPOSES = ("RECOMMEND", "RISK")
CAMPAIGN_MANUAL_STATES = ("RUNNING", "PAUSED", "TERMINATED")
AUDIENCE_MODES = ("GLOBAL", "OVERRIDE")
RISK_POLICY_MODES = ("INHERIT", "OVERRIDE")
AUDIENCE_SEGMENTS = ("ALL", "NEW", "ACTIVE", "DORMANT", "HIGH_REDEEM", "LOW_REDEEM")
RISK_POLICY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CUSTOM")
RISK_HANDLING_STATUSES = ("AUTO_BLOCKED", "PENDING", "RELEASED", "RESTRICTED")
EXPLANATION_SOURCES = ("AI", "TEMPLATE")
CONFIG_OBJECT_TYPES = ("CAMPAIGN", "OPERATOR_SETTINGS", "RISK_POLICY", "ALERT_SETTINGS")
CONFIG_ACTIONS = ("CREATE", "UPDATE", "PAUSE", "RESUME", "TERMINATE")


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Store(Base):
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
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    store_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stores.id"), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # v1 兼容列；CR-002 完成后新裁决使用 risk_restrictions。
    risk_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="ck_users_role"),
        CheckConstraint(_in("status", USER_STATUSES), name="ck_users_status"),
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
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    coupon_type: Mapped[str] = mapped_column(String(16), nullable=False, default="CASH", server_default="CASH")
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default="0"
    )
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    per_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # CR-002：人工状态与时间派生状态正交。
    manual_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="RUNNING", server_default="RUNNING"
    )
    terminated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="GLOBAL", server_default="GLOBAL"
    )
    risk_policy_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="INHERIT", server_default="INHERIT"
    )
    risk_policy_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("risk_policies.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("category", CATEGORIES), name="ck_campaigns_category"),
        CheckConstraint(_in("coupon_type", COUPON_TYPES), name="ck_campaigns_coupon_type"),
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
        CheckConstraint("claimed_count <= total_stock", name="ck_campaigns_no_oversell"),
        CheckConstraint(_in("manual_state", CAMPAIGN_MANUAL_STATES), name="ck_campaigns_manual_state"),
        CheckConstraint("daily_limit IS NULL OR daily_limit > 0", name="ck_campaigns_daily_limit_positive"),
        CheckConstraint(_in("audience_mode", AUDIENCE_MODES), name="ck_campaigns_audience_mode"),
        CheckConstraint(_in("risk_policy_mode", RISK_POLICY_MODES), name="ck_campaigns_risk_policy_mode"),
        CheckConstraint(
            "(manual_state = 'TERMINATED' AND terminated_at IS NOT NULL AND terminated_by IS NOT NULL)"
            " OR (manual_state <> 'TERMINATED' AND terminated_at IS NULL AND terminated_by IS NULL)",
            name="ck_campaigns_termination_consistency",
        ),
        CheckConstraint(
            "(risk_policy_mode = 'OVERRIDE' AND risk_policy_id IS NOT NULL)"
            " OR (risk_policy_mode = 'INHERIT' AND risk_policy_id IS NULL)",
            name="ck_campaigns_risk_policy_consistency",
        ),
        Index("ix_campaigns_window", "start_at", "end_at"),
        Index("ix_campaigns_category", "category"),
    )


class UserCoupon(Base):
    __tablename__ = "user_coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="UNUSED", server_default="UNUSED")
    claimed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    used_store_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stores.id"), nullable=True)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", "seq", name="uq_user_coupons_campaign_user_seq"),
        CheckConstraint(_in("status", COUPON_STATUSES), name="ck_user_coupons_status"),
        CheckConstraint("seq >= 1", name="ck_user_coupons_seq_min"),
        CheckConstraint(
            "(status = 'USED' AND used_at IS NOT NULL AND used_by IS NOT NULL)"
            " OR (status = 'UNUSED' AND used_at IS NULL AND used_by IS NULL)",
            name="ck_user_coupons_used_consistency",
        ),
        Index("ix_user_coupons_campaign_status", "campaign_id", "status"),
        Index("ix_user_coupons_user_claimed_at", "user_id", "claimed_at"),
        Index("ix_user_coupons_claimed_campaign", "claimed_at", "campaign_id"),
        Index(
            "ix_user_coupons_used_campaign",
            "used_at",
            "campaign_id",
            postgresql_where=text("used_at IS NOT NULL"),
        ),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("campaigns.id"), nullable=True)
    window_request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(8), nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ai_invocation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ai_invocations.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    handled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    factor_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    policy_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    explanation_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    handling_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", server_default="PENDING"
    )
    restricted_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("decision", RISK_DECISIONS), name="ck_risk_events_decision"),
        CheckConstraint(_in("decided_by", RISK_DECIDED_BY), name="ck_risk_events_decided_by"),
        CheckConstraint(_in("status", RISK_STATUSES), name="ck_risk_events_status"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_risk_events_score_range",
        ),
        CheckConstraint(
            "explanation_source IS NULL OR explanation_source IN ('AI', 'TEMPLATE')",
            name="ck_risk_events_explanation_source",
        ),
        CheckConstraint(_in("handling_status", RISK_HANDLING_STATUSES), name="ck_risk_events_handling_status"),
        Index("ix_risk_events_created_at", "created_at"),
        Index("ix_risk_events_status", "status"),
        Index("ix_risk_events_user_created", "user_id", "created_at"),
        Index("ix_risk_events_campaign_decision", "created_at", "campaign_id", "decision"),
        Index("ix_risk_events_handling_created", "handling_status", "created_at"),
    )


class AiInvocation(Base):
    __tablename__ = "ai_invocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    degrade_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_in("purpose", AI_PURPOSES), name="ck_ai_invocations_purpose"),
        CheckConstraint(
            "degraded = false OR degrade_reason IS NOT NULL",
            name="ck_ai_invocations_degrade_reason",
        ),
        Index("ix_ai_invocations_purpose_created", "purpose", "created_at"),
    )


class RiskPolicy(Base):
    __tablename__ = "risk_policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    is_global_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    hard_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    factor_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    block_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_in("level", RISK_POLICY_LEVELS), name="ck_risk_policies_level"),
        CheckConstraint("review_threshold >= 0 AND review_threshold <= 99", name="ck_risk_policies_review_threshold"),
        CheckConstraint("block_threshold >= 1 AND block_threshold <= 100", name="ck_risk_policies_block_threshold"),
        CheckConstraint("review_threshold < block_threshold", name="ck_risk_policies_threshold_order"),
        CheckConstraint("version >= 1", name="ck_risk_policies_version"),
        Index(
            "uq_risk_policies_global_default",
            "is_global_default",
            unique=True,
            postgresql_where=text("is_global_default = true"),
        ),
    )


class OperatorSettings(Base):
    __tablename__ = "operator_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audience_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    default_risk_policy_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("risk_policies.id"), nullable=False)
    alert_settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_operator_settings_singleton"),
        CheckConstraint("version >= 1", name="ck_operator_settings_version"),
    )


class CampaignAudience(Base):
    __tablename__ = "campaign_audiences"

    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    segment_code: Mapped[str] = mapped_column(String(32), primary_key=True)

    __table_args__ = (
        CheckConstraint(_in("segment_code", AUDIENCE_SEGMENTS), name="ck_campaign_audiences_segment"),
    )


class CampaignTimeWindow(Base):
    __tablename__ = "campaign_time_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    end_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("start_minute >= 0 AND start_minute <= 1439", name="ck_campaign_time_windows_start"),
        CheckConstraint("end_minute >= 1 AND end_minute <= 1440", name="ck_campaign_time_windows_end"),
        CheckConstraint("end_minute > start_minute", name="ck_campaign_time_windows_order"),
        Index("ix_campaign_time_windows_campaign", "campaign_id"),
    )


class CampaignDailyCounter(Base):
    __tablename__ = "campaign_daily_counters"

    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    business_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("claimed_count >= 0", name="ck_campaign_daily_counters_non_negative"),
    )


class RiskRestriction(Base):
    __tablename__ = "risk_restrictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    source_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("risk_events.id"), nullable=True)
    restricted_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "campaign_id", name="uq_risk_restrictions_user_campaign"),
        Index("ix_risk_restrictions_active", "user_id", "campaign_id", "released_at", "restricted_until"),
    )


class ConfigChangeLog(Base):
    __tablename__ = "config_change_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_in("object_type", CONFIG_OBJECT_TYPES), name="ck_config_change_logs_object_type"),
        CheckConstraint(_in("action", CONFIG_ACTIONS), name="ck_config_change_logs_action"),
        Index("ix_config_change_logs_object_created", "object_type", "object_id", "created_at"),
    )
