"""运营全局设置与配置审计 API（FR-007、FR-055）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import (
    AlertSettingsUpdate,
    AudienceSettingsUpdate,
    ConfigChangeOut,
    OperatorSettingsOut,
    Paged,
    RiskSettingsUpdate,
)
from ..security import require_operator
from ..services import operator_settings as svc

router = APIRouter(prefix="/api/operator/settings", tags=["运营设置"])


@router.get("", response_model=OperatorSettingsOut)
def get_settings(
    db: Session = Depends(get_db), _: User = Depends(require_operator)
) -> OperatorSettingsOut:
    return svc.get(db)


@router.patch("/audiences", response_model=OperatorSettingsOut)
def update_audiences(
    payload: AudienceSettingsUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_operator),
) -> OperatorSettingsOut:
    return svc.update_audiences(
        db,
        expected_version=payload.expected_version,
        thresholds=payload.thresholds,
        operator_id=operator.id,
    )


@router.patch("/risk", response_model=OperatorSettingsOut)
def update_risk(
    payload: RiskSettingsUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_operator),
) -> OperatorSettingsOut:
    return svc.update_risk(
        db,
        expected_version=payload.expected_version,
        level=payload.level,
        custom=payload.custom,
        operator_id=operator.id,
    )


@router.patch("/alerts", response_model=OperatorSettingsOut)
def update_alerts(
    payload: AlertSettingsUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_operator),
) -> OperatorSettingsOut:
    return svc.update_alerts(
        db,
        expected_version=payload.expected_version,
        alerts=payload.settings,
        operator_id=operator.id,
    )


@router.get("/changes", response_model=Paged)
def changes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
) -> Paged:
    rows, total = svc.list_changes(db, page, page_size)
    items = [
        ConfigChangeOut(
            id=log.id,
            object_type=log.object_type,
            object_id=log.object_id,
            action=log.action,
            before_data=log.before_data,
            after_data=log.after_data,
            changed_by=user.username,
            created_at=log.created_at,
        ).model_dump(mode="json")
        for log, user in rows
    ]
    return Paged(items=items, total=total, page=page, page_size=page_size)
