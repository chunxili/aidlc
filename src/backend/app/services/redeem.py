"""核销（FR-020/021/022、ADR-004、ADR-014）。

幂等键**就是券码本身**，不引入 Idempotency-Key：券天生是单次消费资源，
"是否已核销"这一事实存在于券自身。

核销的并发控制仍是单条条件 UPDATE：

    UPDATE user_coupons SET status='USED', ...
     WHERE code=:code AND status='UNUSED' AND expires_at > now()

rowcount=1 成功；rowcount=0 回查券，**按 status 优先、时间其次**判定原因。

引入券型后新增订单金额门槛校验（ADR-014）。**判定顺序：券状态 → 时间 → 金额门槛。**
一张已核销的券即使本次订单金额不达标，也应回「已核销」而非「未达门槛」，
否则核销员会以为换个订单就能再用一次。金额校验是前置条件，不改变幂等来源。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..errors import (
    coupon_already_used,
    coupon_expired,
    coupon_not_found,
    order_amount_below_threshold,
)
from ..models import Campaign, Store, User, UserCoupon
from . import pricing


def _load(db: Session, code: str) -> tuple[UserCoupon, Campaign, User]:
    row = db.execute(
        select(UserCoupon, Campaign, User)
        .join(Campaign, Campaign.id == UserCoupon.campaign_id)
        .join(User, User.id == UserCoupon.user_id)
        .where(UserCoupon.code == code)
    ).first()
    if row is None:
        raise coupon_not_found()
    return row[0], row[1], row[2]


def judge(coupon: UserCoupon, now: dt.datetime | None = None) -> tuple[bool, str | None]:
    """判定券本身能否核销（不含金额门槛）。

    **判定顺序固定：先看 status，再看时间**（终态优先，ADR-004）。
    查验接口与核销接口共用本函数，避免两套口径（FR-021 AC-2）。
    """
    now = now or dt.datetime.now(dt.UTC)
    if coupon.status == "USED":
        return False, "已核销"
    if coupon.expires_at <= now:
        return False, "券已过期"
    return True, None


def check(db: Session, code: str) -> dict:
    """核销前查验。纯读，不改变任何状态（FR-021）。"""
    coupon, campaign, owner = _load(db, code)
    redeemable, reason = judge(coupon)
    from .claim import display_status

    masked = owner.username[0] + "***" + owner.username[-1] if len(owner.username) > 2 else "***"
    return {
        "code": coupon.code,
        "campaign_name": campaign.name,
        "coupon_type": campaign.coupon_type,
        "benefit_text": pricing.describe(campaign),
        "face_value": campaign.face_value,
        "min_order_amount": campaign.min_order_amount,
        "discount_percent": campaign.discount_percent,
        "max_discount_amount": campaign.max_discount_amount,
        "display_status": display_status(coupon),
        "owner": masked,
        "redeemable": redeemable,
        "reason": reason,
    }


def redeem(db: Session, code: str, verifier: User, order_amount: Decimal) -> dict:
    """执行核销。order_amount 为本次订单金额，用于门槛校验与优惠计算。"""
    coupon, campaign, _owner = _load(db, code)

    # 先判券状态与有效期（终态优先），再判金额门槛。
    ok, reason = judge(coupon)
    if not ok:
        raise coupon_already_used() if reason == "已核销" else coupon_expired()

    if not pricing.meets_threshold(campaign, order_amount):
        raise order_amount_below_threshold(campaign.min_order_amount or Decimal(0))

    discount = pricing.compute_discount(campaign, order_amount)

    result = db.execute(
        text(
            "UPDATE user_coupons SET status = 'USED', used_at = now(), used_by = :vid,"
            "       used_store_id = :sid, order_amount = :amount, discount_amount = :discount"
            " WHERE code = :code AND status = 'UNUSED' AND expires_at > now()"
        ),
        {
            "code": code,
            "vid": verifier.id,
            "sid": verifier.store_id,
            "amount": order_amount,
            "discount": discount,
        },
    )
    if result.rowcount == 1:
        db.commit()
        # 上面走的是原生 UPDATE，ORM 身份映射里的旧对象不会自动失效；
        # 加上 expire_on_commit=False，直接重查会拿到 used_at 仍为 None 的陈旧对象。
        # 显式失效后再读，才能取到刚写入的核销事实。
        db.expire_all()
        coupon, campaign, _ = _load(db, code)
        store = db.get(Store, coupon.used_store_id) if coupon.used_store_id else None
        return {
            "code": coupon.code,
            "benefit_text": pricing.describe(campaign),
            "order_amount": coupon.order_amount,
            "discount_amount": coupon.discount_amount,
            "payable_amount": (coupon.order_amount or Decimal(0)) - (coupon.discount_amount or Decimal(0)),
            "used_at": coupon.used_at,
            "used_by": verifier.display_name,
            "store_name": store.name if store else None,
        }

    db.rollback()
    # rowcount=0：并发下已被他人核销，或恰好在校验后过期。回查后按 status 优先判定。
    coupon, _campaign, _owner = _load(db, code)
    if coupon.status == "USED":
        raise coupon_already_used()
    raise coupon_expired()
