"""领券事务（FR-010）。项目最核心的一段代码。

设计依据：system-architecture.md 第三节时序图。**语句顺序即设计**，不可调整：

    BEGIN
      UPDATE campaign SET claimed_count = claimed_count + 1
        WHERE id = ? AND claimed_count < total_stock      -- rowcount=0 → 库存不足
      seq = 该用户已领数 + 1；seq > per_user_limit → 已达上限
      INSERT user_coupon(... seq ...)                     -- 唯一冲突 → 已达上限
    COMMIT

两个约束落在不同表上，跨表约束的并发正确性完全交给 PostgreSQL（ADR-001）：
- 库存：条件 UPDATE 的受影响行数即判定结果，无 SELECT-then-UPDATE 的竞态窗口
- 限领：UNIQUE(campaign_id, user_id, seq) 拒绝并发下算出同一 seq 的第二个请求

唯一冲突触发回滚时，库存的 +1 随事务一并撤销，**因此不需要任何补偿逻辑**。
应用层不实现锁、队列或串行化。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import (
    campaign_not_active,
    campaign_not_found,
    out_of_stock,
    per_user_limit_reached,
)
from ..models import Campaign, UserCoupon
from .campaign import derive_status
from .coupon_code import generate_unique_code


def display_status(c: UserCoupon, now: dt.datetime | None = None) -> str:
    """派生展示状态。"已过期"永不落库（INV-3、ADR-002）。"""
    now = now or dt.datetime.now(dt.UTC)
    if c.status == "USED":
        return "已核销"
    return "可用" if c.expires_at > now else "已过期"


def compute_expires_at(campaign: Campaign, claimed_at: dt.datetime) -> dt.datetime:
    """expires_at = min(活动结束时间, 领取时间 + 有效时长)（ADR-003）。

    该值依赖领取时刻，必须在领取时计算并落库，无法事后重算。
    注意与"是否已过期"区分：后者是对本值的实时比较，永不落库。
    """
    candidate = claimed_at + dt.timedelta(minutes=campaign.validity_minutes)
    return min(campaign.end_at, candidate)


def claim(db: Session, campaign_id: int, user_id: int) -> UserCoupon:
    """执行一次领券。调用方须已完成风控前置（风控在事务之外）。"""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise campaign_not_found()
    if derive_status(campaign) != "ACTIVE":
        raise campaign_not_active()

    per_user_limit = campaign.per_user_limit

    try:
        # 步骤 1：条件 UPDATE 扣库存。判定依据是**受影响行数**。
        result = db.execute(
            text(
                "UPDATE campaigns SET claimed_count = claimed_count + 1"
                " WHERE id = :cid AND claimed_count < total_stock"
            ),
            {"cid": campaign_id},
        )
        if result.rowcount == 0:
            db.rollback()
            raise out_of_stock()

        # 步骤 2：算 seq 并校验个人上限。
        already = db.execute(
            select(func.count(UserCoupon.id)).where(
                UserCoupon.campaign_id == campaign_id, UserCoupon.user_id == user_id
            )
        ).scalar_one()
        seq = already + 1
        if seq > per_user_limit:
            db.rollback()  # 库存的 +1 随之撤销
            raise per_user_limit_reached()

        # 步骤 3~5：生成券码、计算 expires_at、插入。
        claimed_at = dt.datetime.now(dt.UTC)
        coupon = UserCoupon(
            campaign_id=campaign_id,
            user_id=user_id,
            seq=seq,
            code=generate_unique_code(db),
            status="UNUSED",
            claimed_at=claimed_at,
            expires_at=compute_expires_at(campaign, claimed_at),
        )
        db.add(coupon)
        db.commit()
    except IntegrityError as exc:
        # 并发下两个请求算出同一个 seq：唯一索引拒绝其一。
        # 回滚使库存的 +1 自动撤销，无需补偿。
        db.rollback()
        if "uq_user_coupons_campaign_user_seq" in str(exc.orig):
            raise per_user_limit_reached() from None
        if "ck_campaigns_no_oversell" in str(exc.orig):
            # 数据库级兜底被触发，说明条件 UPDATE 被绕过了，按库存不足对外表达。
            raise out_of_stock() from None
        raise

    db.refresh(coupon)
    return coupon


def list_my_coupons(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    display_filter: str | None = None,
) -> tuple[list[tuple[UserCoupon, Campaign]], int]:
    """我的券。

    过滤条件强制取自 token 的用户 id，**忽略客户端传入的任何 user_id**（FR-011）。
    """
    stmt = (
        select(UserCoupon, Campaign)
        .join(Campaign, Campaign.id == UserCoupon.campaign_id)
        .where(UserCoupon.user_id == user_id)
        .order_by(UserCoupon.claimed_at.desc())
    )
    rows = list(db.execute(stmt).all())
    if display_filter:
        rows = [(c, camp) for c, camp in rows if display_status(c) == display_filter]
    total = len(rows)
    start = (page - 1) * page_size
    return [(r[0], r[1]) for r in rows[start : start + page_size]], total
