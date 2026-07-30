"""统计路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import CampaignStatsOut, IntegrityOut, OverviewOut
from ..security import require_admin, require_admin_or_operator
from ..services import stats as svc

router = APIRouter(prefix="/api/stats", tags=["统计"])


@router.get("/overview", response_model=OverviewOut)
def overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> OverviewOut:
    return svc.overview(db)


@router.get("/integrity", response_model=IntegrityOut)
def integrity(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> IntegrityOut:
    """对账自检：INV-1 库存守恒与 INV-2 券的完全划分。"""
    return svc.integrity(db)


@router.get("/campaigns/{campaign_id}", response_model=CampaignStatsOut)
def campaign_stats(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_or_operator),
) -> CampaignStatsOut:
    return svc.campaign_stats(db, campaign_id)
