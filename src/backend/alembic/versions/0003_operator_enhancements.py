"""operator enhancement configuration foundation

CR-002 / T-15：活动人工状态、投放配置、风控策略、活动级限制与配置审计。

Revision ID: 0003_operator
Revises: 0002_product
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_operator"
down_revision: str | None = "0002_product"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # 风控策略先建，campaigns/operator_settings 均引用它。
    op.create_table(
        "risk_policies",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("is_global_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("hard_rules", JSON, nullable=False),
        sa.Column("factor_weights", JSON, nullable=False),
        sa.Column("review_threshold", sa.Integer(), nullable=False),
        sa.Column("block_threshold", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("level IN ('LOW','MEDIUM','HIGH','CUSTOM')", name="ck_risk_policies_level"),
        sa.CheckConstraint("review_threshold BETWEEN 0 AND 99", name="ck_risk_policies_review_threshold"),
        sa.CheckConstraint("block_threshold BETWEEN 1 AND 100", name="ck_risk_policies_block_threshold"),
        sa.CheckConstraint("review_threshold < block_threshold", name="ck_risk_policies_threshold_order"),
        sa.CheckConstraint("version >= 1", name="ck_risk_policies_version"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "uq_risk_policies_global_default",
        "risk_policies",
        ["is_global_default"],
        unique=True,
        postgresql_where=sa.text("is_global_default = true"),
    )

    # 活动兼容字段：旧活动自动成为 RUNNING + 无日额度 + 继承策略。
    op.add_column("campaigns", sa.Column("manual_state", sa.String(16), server_default="RUNNING", nullable=False))
    op.add_column("campaigns", sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("terminated_by", sa.BigInteger(), nullable=True))
    op.add_column("campaigns", sa.Column("daily_limit", sa.Integer(), nullable=True))
    op.add_column("campaigns", sa.Column("audience_mode", sa.String(16), server_default="GLOBAL", nullable=False))
    op.add_column("campaigns", sa.Column("risk_policy_mode", sa.String(16), server_default="INHERIT", nullable=False))
    op.add_column("campaigns", sa.Column("risk_policy_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_campaigns_terminated_by", "campaigns", "users", ["terminated_by"], ["id"])
    op.create_foreign_key("fk_campaigns_risk_policy", "campaigns", "risk_policies", ["risk_policy_id"], ["id"])
    op.create_check_constraint("ck_campaigns_manual_state", "campaigns", "manual_state IN ('RUNNING','PAUSED','TERMINATED')")
    op.create_check_constraint("ck_campaigns_daily_limit_positive", "campaigns", "daily_limit IS NULL OR daily_limit > 0")
    op.create_check_constraint("ck_campaigns_audience_mode", "campaigns", "audience_mode IN ('GLOBAL','OVERRIDE')")
    op.create_check_constraint("ck_campaigns_risk_policy_mode", "campaigns", "risk_policy_mode IN ('INHERIT','OVERRIDE')")
    op.create_check_constraint(
        "ck_campaigns_termination_consistency",
        "campaigns",
        "(manual_state = 'TERMINATED' AND terminated_at IS NOT NULL AND terminated_by IS NOT NULL)"
        " OR (manual_state <> 'TERMINATED' AND terminated_at IS NULL AND terminated_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_campaigns_risk_policy_consistency",
        "campaigns",
        "(risk_policy_mode = 'OVERRIDE' AND risk_policy_id IS NOT NULL)"
        " OR (risk_policy_mode = 'INHERIT' AND risk_policy_id IS NULL)",
    )

    op.create_table(
        "campaign_audiences",
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("segment_code", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "segment_code IN ('ALL','NEW','ACTIVE','DORMANT','HIGH_REDEEM','LOW_REDEEM')",
            name="ck_campaign_audiences_segment",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "segment_code"),
    )
    # 每个历史活动显式回填 ALL，便于后续统一求值。
    op.execute("INSERT INTO campaign_audiences(campaign_id, segment_code) SELECT id, 'ALL' FROM campaigns")

    op.create_table(
        "campaign_time_windows",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("start_minute BETWEEN 0 AND 1439", name="ck_campaign_time_windows_start"),
        sa.CheckConstraint("end_minute BETWEEN 1 AND 1440", name="ck_campaign_time_windows_end"),
        sa.CheckConstraint("end_minute > start_minute", name="ck_campaign_time_windows_order"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_time_windows_campaign", "campaign_time_windows", ["campaign_id"])

    op.create_table(
        "campaign_daily_counters",
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("claimed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("claimed_count >= 0", name="ck_campaign_daily_counters_non_negative"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "business_date"),
    )

    op.create_table(
        "operator_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audience_thresholds", JSON, nullable=False),
        sa.Column("default_risk_policy_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_settings", JSON, nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_operator_settings_singleton"),
        sa.CheckConstraint("version >= 1", name="ck_operator_settings_version"),
        sa.ForeignKeyConstraint(["default_risk_policy_id"], ["risk_policies.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # 风险事件 v2 快照。旧数据按 decision 映射处理状态。
    op.add_column("risk_events", sa.Column("factor_breakdown", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("risk_events", sa.Column("evidence_snapshot", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("risk_events", sa.Column("policy_snapshot", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("risk_events", sa.Column("explanation_source", sa.String(16), nullable=True))
    op.add_column("risk_events", sa.Column("recommended_action", sa.Text(), nullable=True))
    op.add_column("risk_events", sa.Column("handling_status", sa.String(20), server_default="PENDING", nullable=False))
    op.add_column("risk_events", sa.Column("restricted_until", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE risk_events SET handling_status = CASE"
        " WHEN decision = 'BLOCK' THEN 'AUTO_BLOCKED'"
        " WHEN status = 'RELEASED' THEN 'RELEASED'"
        " WHEN status = 'KEPT' THEN 'RESTRICTED' ELSE 'PENDING' END"
    )
    op.create_check_constraint(
        "ck_risk_events_explanation_source",
        "risk_events",
        "explanation_source IS NULL OR explanation_source IN ('AI','TEMPLATE')",
    )
    op.create_check_constraint(
        "ck_risk_events_handling_status",
        "risk_events",
        "handling_status IN ('AUTO_BLOCKED','PENDING','RELEASED','RESTRICTED')",
    )
    op.create_index("ix_risk_events_campaign_decision", "risk_events", ["created_at", "campaign_id", "decision"])
    op.create_index("ix_risk_events_handling_created", "risk_events", ["handling_status", "created_at"])

    op.create_table(
        "risk_restrictions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("restricted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["risk_events.id"]),
        sa.ForeignKeyConstraint(["released_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "campaign_id", name="uq_risk_restrictions_user_campaign"),
    )
    op.create_index(
        "ix_risk_restrictions_active",
        "risk_restrictions",
        ["user_id", "campaign_id", "released_at", "restricted_until"],
    )
    # 只迁移能明确关联活动的旧未解除人工标记；绝不扩散成全局限制。
    op.execute(
        "INSERT INTO risk_restrictions(user_id,campaign_id,source_event_id,restricted_until)"
        " SELECT DISTINCT ON (user_id,campaign_id) user_id,campaign_id,id,NULL"
        " FROM risk_events WHERE campaign_id IS NOT NULL AND status IN ('PENDING','KEPT')"
        " AND decision = 'MANUAL_REVIEW' ORDER BY user_id,campaign_id,created_at DESC"
        " ON CONFLICT (user_id,campaign_id) DO NOTHING"
    )

    op.create_table(
        "config_change_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before_data", JSON, nullable=False),
        sa.Column("after_data", JSON, nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "object_type IN ('CAMPAIGN','OPERATOR_SETTINGS','RISK_POLICY','ALERT_SETTINGS')",
            name="ck_config_change_logs_object_type",
        ),
        sa.CheckConstraint(
            "action IN ('CREATE','UPDATE','PAUSE','RESUME','TERMINATE')",
            name="ck_config_change_logs_action",
        ),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_config_change_logs_object_created",
        "config_change_logs",
        ["object_type", "object_id", "created_at"],
    )

    op.create_index("ix_user_coupons_claimed_campaign", "user_coupons", ["claimed_at", "campaign_id"])
    op.create_index(
        "ix_user_coupons_used_campaign",
        "user_coupons",
        ["used_at", "campaign_id"],
        postgresql_where=sa.text("used_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_coupons_used_campaign", table_name="user_coupons")
    op.drop_index("ix_user_coupons_claimed_campaign", table_name="user_coupons")

    op.drop_index("ix_config_change_logs_object_created", table_name="config_change_logs")
    op.drop_table("config_change_logs")
    op.drop_index("ix_risk_restrictions_active", table_name="risk_restrictions")
    op.drop_table("risk_restrictions")

    op.drop_index("ix_risk_events_handling_created", table_name="risk_events")
    op.drop_index("ix_risk_events_campaign_decision", table_name="risk_events")
    op.drop_constraint("ck_risk_events_handling_status", "risk_events", type_="check")
    op.drop_constraint("ck_risk_events_explanation_source", "risk_events", type_="check")
    for col in (
        "restricted_until",
        "handling_status",
        "recommended_action",
        "explanation_source",
        "policy_snapshot",
        "evidence_snapshot",
        "factor_breakdown",
    ):
        op.drop_column("risk_events", col)

    op.drop_table("operator_settings")
    op.drop_table("campaign_daily_counters")
    op.drop_index("ix_campaign_time_windows_campaign", table_name="campaign_time_windows")
    op.drop_table("campaign_time_windows")
    op.drop_table("campaign_audiences")

    op.drop_constraint("ck_campaigns_risk_policy_consistency", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_termination_consistency", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_risk_policy_mode", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_audience_mode", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_daily_limit_positive", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_manual_state", "campaigns", type_="check")
    op.drop_constraint("fk_campaigns_risk_policy", "campaigns", type_="foreignkey")
    op.drop_constraint("fk_campaigns_terminated_by", "campaigns", type_="foreignkey")
    for col in (
        "risk_policy_id",
        "risk_policy_mode",
        "audience_mode",
        "daily_limit",
        "terminated_by",
        "terminated_at",
        "manual_state",
    ):
        op.drop_column("campaigns", col)

    op.drop_index("uq_risk_policies_global_default", table_name="risk_policies")
    op.drop_table("risk_policies")
