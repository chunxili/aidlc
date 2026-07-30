"""stores, account status, coupon types

产品化改造（CR-001）：门店主数据、账号状态与口令、券型与使用门槛、核销事实快照。

autogenerate 不会生成 CHECK 约束，本迁移中的 CHECK 全部手工补齐 ——
"按券型必填""门店只属核销员"这两组规则必须由数据库强制，
留给应用层判断会出现"没有门店的核销员"或"没有折扣上限的折扣券"这类无效数据。

Revision ID: 0002_product
Revises: 0001_init
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_product"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- 门店主数据 ----------
    op.create_table(
        "stores",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("district", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_stores_district", "stores", ["district"])

    # ---------- 活动：券型与门槛 ----------
    op.add_column(
        "campaigns",
        sa.Column("coupon_type", sa.String(length=16), server_default="CASH", nullable=False),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "min_order_amount",
            sa.Numeric(precision=10, scale=2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column("campaigns", sa.Column("discount_percent", sa.Integer(), nullable=True))
    op.add_column(
        "campaigns", sa.Column("max_discount_amount", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    # face_value 改为可空：折扣券不使用该字段
    op.alter_column(
        "campaigns",
        "face_value",
        existing_type=sa.NUMERIC(precision=10, scale=2),
        nullable=True,
    )
    # 原 0001 的 face_value > 0 约束不再适用（折扣券该列为 NULL），替换为按券型的条件约束
    op.drop_constraint("ck_campaigns_face_value_positive", "campaigns", type_="check")
    op.create_check_constraint(
        "ck_campaigns_coupon_type", "campaigns", "coupon_type IN ('CASH', 'DISCOUNT')"
    )
    op.create_check_constraint(
        "ck_campaigns_cash_requires_face_value",
        "campaigns",
        "coupon_type <> 'CASH' OR (face_value IS NOT NULL AND face_value > 0)",
    )
    op.create_check_constraint(
        "ck_campaigns_discount_requires_percent_and_cap",
        "campaigns",
        "coupon_type <> 'DISCOUNT' OR (discount_percent IS NOT NULL"
        " AND discount_percent BETWEEN 1 AND 99"
        " AND max_discount_amount IS NOT NULL AND max_discount_amount > 0)",
    )
    op.create_check_constraint(
        "ck_campaigns_min_order_non_negative", "campaigns", "min_order_amount >= 0"
    )

    # ---------- 券：核销事实快照 ----------
    op.add_column("user_coupons", sa.Column("used_store_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "user_coupons", sa.Column("order_amount", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column(
        "user_coupons",
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_coupons_used_store", "user_coupons", "stores", ["used_store_id"], ["id"]
    )

    # ---------- 账号：口令、状态、门店归属、审核留痕 ----------
    op.add_column("users", sa.Column("password_hash", sa.String(length=256), nullable=True))
    op.add_column(
        "users", sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False)
    )
    op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("store_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("reviewed_by", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("reject_reason", sa.String(length=256), nullable=True))
    op.create_index("ix_users_status_role", "users", ["status", "role"])
    op.create_index("ix_users_store", "users", ["store_id"])
    op.create_foreign_key("fk_users_reviewed_by", "users", "users", ["reviewed_by"], ["id"])
    op.create_foreign_key("fk_users_store", "users", "stores", ["store_id"], ["id"])
    op.create_check_constraint(
        "ck_users_status", "users", "status IN ('ACTIVE', 'PENDING', 'REJECTED')"
    )

    # 先插入一个引导门店并回填既有核销员，再加约束。
    # 0001 时代的核销员没有门店归属，直接加约束会被既有数据拒绝
    # （实测：check constraint ... is violated by some row）。
    # 引导门店的编码与 seed 的首个门店一致，seed 会以 ON CONFLICT 补齐其余字段。
    op.execute(
        "INSERT INTO stores(code, name, district, address)"
        " VALUES ('GZ-TH-001', '天河体育中心店', '天河区', '广州市天河区天河路 299 号')"
        " ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        "UPDATE users SET store_id = (SELECT id FROM stores WHERE code = 'GZ-TH-001')"
        " WHERE role = 'VERIFIER' AND store_id IS NULL"
    )
    # 反向也要清理：非核销员若被误挂门店，同样会违反约束
    op.execute("UPDATE users SET store_id = NULL WHERE role <> 'VERIFIER'")

    op.create_check_constraint(
        "ck_users_store_only_for_verifier",
        "users",
        "(role = 'VERIFIER' AND store_id IS NOT NULL)"
        " OR (role <> 'VERIFIER' AND store_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_store_only_for_verifier", "users", type_="check")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_constraint("fk_users_store", "users", type_="foreignkey")
    op.drop_constraint("fk_users_reviewed_by", "users", type_="foreignkey")
    op.drop_index("ix_users_store", table_name="users")
    op.drop_index("ix_users_status_role", table_name="users")
    for col in (
        "reject_reason",
        "reviewed_at",
        "reviewed_by",
        "store_id",
        "phone",
        "status",
        "password_hash",
    ):
        op.drop_column("users", col)

    op.drop_constraint("fk_user_coupons_used_store", "user_coupons", type_="foreignkey")
    for col in ("discount_amount", "order_amount", "used_store_id"):
        op.drop_column("user_coupons", col)

    op.drop_constraint("ck_campaigns_min_order_non_negative", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_discount_requires_percent_and_cap", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_cash_requires_face_value", "campaigns", type_="check")
    op.drop_constraint("ck_campaigns_coupon_type", "campaigns", type_="check")
    # 回退前折扣券的 face_value 为 NULL，无法直接恢复 NOT NULL；
    # 先按券型回填一个占位值再恢复约束，避免 downgrade 失败。
    op.execute("UPDATE campaigns SET face_value = 0.01 WHERE face_value IS NULL")
    op.alter_column(
        "campaigns",
        "face_value",
        existing_type=sa.NUMERIC(precision=10, scale=2),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_campaigns_face_value_positive", "campaigns", "face_value > 0"
    )
    for col in ("max_discount_amount", "discount_percent", "min_order_amount", "coupon_type"):
        op.drop_column("campaigns", col)

    op.drop_index("ix_stores_district", table_name="stores")
    op.drop_table("stores")
