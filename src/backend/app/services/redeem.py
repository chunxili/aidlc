"""核销（FR-020/021、ADR-004）。

幂等键**就是券码本身**，不引入 Idempotency-Key：券天生是单次消费资源，
"是否已核销"这一事实存在于券自身。引入外部幂等键会派生"同一张券用两个不同 key
核销算不算重复"这类自找的问题，其答案最终仍要回到券的状态机。

单条条件 UPDATE 即完成全部并发控制：

    UPDATE user_coupons SET status='USED', used_at=now(), used_by=:vid
     WHERE code=:code AND status='UNUSED' AND expires_at > now()

rowcount=1 成功；rowcount=0 回查券，**按 status 优先、时间其次**判定原因。

终态优先：已核销的券过期后再核销返回"已核销"。核销已发生且不可撤销；"过期"
描述的是未被使用的券失去资格，对已消费的券不成立。返回"券已过期"会误导核销人员
以为该券未被使用。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..errors import coupon_already_used, coupon_expired, coupon_not_found
from ..models import Campaign, User, UserCoupon


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
    """判定券能否核销及原因。

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
        "face_value": campaign.face_value,
        "display_status": display_status(coupon),
        "owner": masked,
        "redeemable": redeemable,
        "reason": reason,
    }


def redeem(db: Session, code: str, verifier: User) -> dict:
    """执行核销。"""
    result = db.execute(
        text(
            "UPDATE user_coupons SET status = 'USED', used_at = now(), used_by = :vid"
            " WHERE code = :code AND status = 'UNUSED' AND expires_at > now()"
        ),
        {"code": code, "vid": verifier.id},
    )
    if result.rowcount == 1:
        db.commit()
        coupon, campaign, _ = _load(db, code)
        return {
            "code": coupon.code,
            "face_value": campaign.face_value,
            "used_at": coupon.used_at,
            "used_by": verifier.username,
        }

    db.rollback()
    # rowcount=0：回查券，按 status 优先判定具体原因。
    coupon, _campaign, _owner = _load(db, code)
    if coupon.status == "USED":
        raise coupon_already_used()
    raise coupon_expired()
