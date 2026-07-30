"""管理员后台：注册审核与核销人员名册（FR-066、FR-067）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import PendingUserOut, ReviewIn, VerifierOut
from ..security import require_admin
from ..services import account as svc

router = APIRouter(prefix="/api/admin", tags=["管理"])


@router.get("/registrations", response_model=list[PendingUserOut])
def pending_registrations(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[PendingUserOut]:
    """待审核的注册申请（核销人员与运营人员）。"""
    return [
        PendingUserOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role,
            phone=u.phone,
            store_id=u.store_id,
            store_name=s.name if s else None,
            store_district=s.district if s else None,
            created_at=u.created_at,
        )
        for u, s in svc.list_pending(db)
    ]


@router.post("/registrations/{user_id}/review", response_model=PendingUserOut)
def review_registration(
    user_id: int,
    payload: ReviewIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> PendingUserOut:
    """审批注册申请。幂等：重复审批返回当前状态。"""
    from ..models import Store

    user = svc.review(db, user_id, payload.approve, admin, payload.reason)
    store = db.get(Store, user.store_id) if user.store_id else None
    return PendingUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        phone=user.phone,
        store_id=user.store_id,
        store_name=store.name if store else None,
        store_district=store.district if store else None,
        created_at=user.created_at,
    )


@router.get("/verifiers", response_model=list[VerifierOut])
def verifiers(
    district: str | None = Query(None),
    store_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[VerifierOut]:
    """全门店核销人员名册，含各人累计核销数。"""
    return [
        VerifierOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            phone=u.phone,
            status=u.status,
            store_id=s.id,
            store_code=s.code,
            store_name=s.name,
            store_district=s.district,
            redeemed_count=cnt,
            created_at=u.created_at,
        )
        for u, s, cnt in svc.list_verifiers(db, district, store_id)
    ]
