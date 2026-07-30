"""领券与我的券路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Campaign, User, UserCoupon
from ..schemas import ClaimIn, ClaimOut, CouponOut, Paged, RiskOut
from ..security import require_user
from ..services import claim as svc
from ..services import risk as risk_svc

router = APIRouter(prefix="/api/coupons", tags=["领券"])


def _coupon_out(c: UserCoupon, campaign: Campaign) -> CouponOut:
    return CouponOut(
        id=c.id,
        code=c.code,
        campaign_id=c.campaign_id,
        campaign_name=campaign.name,
        face_value=campaign.face_value,
        status=c.status,
        display_status=svc.display_status(c),
        seq=c.seq,
        claimed_at=c.claimed_at,
        expires_at=c.expires_at,
    )


@router.post("/claim", response_model=ClaimOut, status_code=201)
def claim(
    payload: ClaimIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> ClaimOut:
    """领取一张券。

    风控前置在**事务之外**先行（ADR-005）：它可能触发外部网络调用，绝不能把
    网络延迟包进持有 campaign 行锁的事务里。
    """
    assessment = risk_svc.assess(db, user, payload.campaign_id)
    risk_svc.raise_if_denied(assessment)

    coupon = svc.claim(db, payload.campaign_id, user.id)
    campaign = db.get(Campaign, coupon.campaign_id)
    return ClaimOut(
        coupon=_coupon_out(coupon, campaign),
        risk=RiskOut(
            score=assessment.score,
            decision=assessment.decision,
            decided_by=assessment.decided_by,
            degraded=assessment.degraded,
            reason=assessment.reason,
        ),
    )


@router.get("/my", response_model=Paged)
def my_coupons(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    display_status: str | None = Query(None, pattern="^(可用|已核销|已过期)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Paged:
    rows, total = svc.list_my_coupons(db, user.id, page, page_size, display_status)
    return Paged(
        items=[_coupon_out(c, camp).model_dump(mode="json") for c, camp in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
