"""活动管理业务规则（FR-001/002/003）。

关键设计：活动状态**不落库**，由 start_at/end_at 与 now() 实时派生（ADR-002）。
落库要么起定时任务扫表刷状态，要么读时惰性回写，前者在单机部署下多一个调度器
且刷库之前状态是错的，后者产生写放大。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BusinessError, campaign_not_found, field_immutable, stock_cannot_decrease
from ..models import Campaign, UserCoupon
from ..schemas import CampaignCreate, CampaignOut, CampaignUpdate
from . import pricing


def derive_status(c: Campaign, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    if now < c.start_at:
        return "PENDING"
    if now > c.end_at:
        return "ENDED"
    return "ACTIVE"


def to_out(c: Campaign) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        name=c.name,
        category=c.category,
        coupon_type=c.coupon_type,
        face_value=c.face_value,
        min_order_amount=c.min_order_amount,
        discount_percent=c.discount_percent,
        max_discount_amount=c.max_discount_amount,
        benefit_text=pricing.describe(c),
        total_stock=c.total_stock,
        claimed_count=c.claimed_count,
        # 恒等式，不存字段（INV-1）
        remaining_stock=c.total_stock - c.claimed_count,
        status=derive_status(c),
        start_at=c.start_at,
        end_at=c.end_at,
        validity_minutes=c.validity_minutes,
        per_user_limit=c.per_user_limit,
    )


def create_campaign(db: Session, payload: CampaignCreate, operator_id: int) -> Campaign:
    """创建活动。**不预生成任何券记录**（ADR-001 计数器模型）。

    end_at > start_at 等约束在 schema 与数据库两侧都有，此处只做 schema
    表达不了的跨字段校验。
    """
    if payload.end_at <= payload.start_at:
        raise BusinessError(400, "VALIDATION_ERROR", "结束时间必须晚于开始时间")

    # 按券型校验必填字段。数据库亦有 CHECK 兜底，此处提前给出可读的业务错误，
    # 避免让 IntegrityError 以 500 的形式冒到用户面前。
    if payload.coupon_type == "CASH":
        if payload.face_value is None:
            raise BusinessError(400, "VALIDATION_ERROR", "满减券必须设置减免金额")
        if payload.discount_percent is not None or payload.max_discount_amount is not None:
            raise BusinessError(400, "VALIDATION_ERROR", "满减券无需设置折扣比例与封顶金额")
    else:
        if payload.discount_percent is None or payload.max_discount_amount is None:
            raise BusinessError(
                400, "VALIDATION_ERROR", "折扣券必须设置折扣比例与优惠封顶金额"
            )
        if payload.face_value is not None:
            raise BusinessError(400, "VALIDATION_ERROR", "折扣券无需设置减免金额")

    c = Campaign(
        name=payload.name,
        category=payload.category,
        coupon_type=payload.coupon_type,
        face_value=payload.face_value,
        min_order_amount=payload.min_order_amount,
        discount_percent=payload.discount_percent,
        max_discount_amount=payload.max_discount_amount,
        total_stock=payload.total_stock,
        claimed_count=0,
        start_at=payload.start_at,
        end_at=payload.end_at,
        validity_minutes=payload.validity_minutes,
        per_user_limit=payload.per_user_limit,
        created_by=operator_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def get_campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise campaign_not_found()
    return c


def update_campaign(db: Session, campaign_id: int, payload: CampaignUpdate) -> Campaign:
    """编辑活动。库存只增。

    库存只增的理由：调低会使 claimed_count > total_stock，直接破坏 INV-1，
    数据库的 CHECK 也会拒绝。此处提前给出可读的业务错误而不是让 500 冒出来。
    """
    c = get_campaign(db, campaign_id)
    data = payload.model_dump(exclude_unset=True)

    if "total_stock" in data and data["total_stock"] is not None:
        if data["total_stock"] < c.total_stock:
            raise stock_cannot_decrease()

    if "end_at" in data and data["end_at"] is not None:
        if data["end_at"] <= c.start_at:
            raise field_immutable("end_at", "结束时间必须晚于开始时间")

    for field, value in data.items():
        if value is not None:
            setattr(c, field, value)
    c.updated_at = dt.datetime.now(dt.UTC)
    db.commit()
    db.refresh(c)
    return c


def list_campaigns(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    category: str | None = None,
) -> tuple[list[Campaign], int]:
    stmt = select(Campaign).order_by(Campaign.id.desc())
    if category:
        stmt = stmt.where(Campaign.category == category)
    rows = list(db.execute(stmt).scalars().all())
    # 状态是派生值，无法下推到 SQL 的 WHERE（ADR-002 的已知代价）。
    # 演示级数据量下在内存过滤成本可忽略；数据量增大时可改为按时间区间下推。
    if status_filter:
        rows = [c for c in rows if derive_status(c) == status_filter]
    total = len(rows)
    start = (page - 1) * page_size
    return rows[start : start + page_size], total


def list_available_for_user(db: Session, user_id: int) -> list[tuple[Campaign, int]]:
    """USER 视图：进行中 + 有库存 + 该用户未领满。

    返回 (活动, 该用户已领数)，供前端展示"剩余可领 N 次"。
    """
    now = dt.datetime.now(dt.UTC)
    stmt = (
        select(Campaign)
        .where(
            Campaign.start_at <= now,
            Campaign.end_at >= now,
            Campaign.claimed_count < Campaign.total_stock,
        )
        .order_by(Campaign.id.desc())
    )
    campaigns = list(db.execute(stmt).scalars().all())
    if not campaigns:
        return []

    counts = dict(
        db.execute(
            select(UserCoupon.campaign_id, func.count(UserCoupon.id))
            .where(
                UserCoupon.user_id == user_id,
                UserCoupon.campaign_id.in_([c.id for c in campaigns]),
            )
            .group_by(UserCoupon.campaign_id)
        ).all()
    )
    return [
        (c, counts.get(c.id, 0))
        for c in campaigns
        if counts.get(c.id, 0) < c.per_user_limit
    ]
