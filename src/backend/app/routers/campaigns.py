"""活动管理路由。角色声明严格对应 api-specification.md 第十节映射表。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import (
    AvailableCampaignOut,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    Paged,
)
from ..security import require_admin_or_operator, require_operator, require_user
from ..services import campaign as svc

router = APIRouter(prefix="/api/campaigns", tags=["活动管理"])


@router.post("", response_model=CampaignOut, status_code=201)
def create(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    op: User = Depends(require_operator),
) -> CampaignOut:
    return svc.to_out(svc.create_campaign(db, payload, op.id))


@router.get("", response_model=Paged)
def list_all(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(PENDING|ACTIVE|ENDED)$"),
    category: str | None = Query(None, pattern="^(FOOD|TRAVEL|SHOPPING|LIFE)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_or_operator),
) -> Paged:
    rows, total = svc.list_campaigns(db, page, page_size, status, category)
    return Paged(
        items=[svc.to_out(c).model_dump(mode="json") for c in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/available", response_model=list[AvailableCampaignOut])
def available(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[AvailableCampaignOut]:
    """当前可领的活动。不下发统计与风控字段（最小权限）。"""
    return [
        AvailableCampaignOut(
            id=c.id,
            name=c.name,
            category=c.category,
            face_value=c.face_value,
            remaining_stock=c.total_stock - c.claimed_count,
            end_at=c.end_at,
            validity_minutes=c.validity_minutes,
            per_user_limit=c.per_user_limit,
            my_claimed_count=mine,
        )
        for c, mine in svc.list_available_for_user(db, user.id)
    ]


@router.get("/{campaign_id}", response_model=CampaignOut)
def detail(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_or_operator),
) -> CampaignOut:
    return svc.to_out(svc.get_campaign(db, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update(
    campaign_id: int,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
) -> CampaignOut:
    return svc.to_out(svc.update_campaign(db, campaign_id, payload))
