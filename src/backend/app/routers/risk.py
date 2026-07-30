"""风险标记审核路由（FR-052）。

**不存在"批准发券"接口**：审核对象是风险标记，不是待批领取；
系统不代为补发，用户走正常领取路径（ADR-007）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import Paged, RiskEventOut, RiskHandleIn
from ..security import require_operator
from ..services import risk as svc

router = APIRouter(prefix="/api/risk", tags=["风控"])


def _to_out(event, user, db: Session) -> RiskEventOut:
    handler = db.get(User, event.handled_by) if event.handled_by else None
    return RiskEventOut(
        id=event.id,
        user_id=event.user_id,
        username=user.username,
        campaign_id=event.campaign_id,
        window_request_count=event.window_request_count,
        risk_score=event.risk_score,
        decision=event.decision,
        decided_by=event.decided_by,
        degraded=event.degraded,
        # 必需字段：运营看不到判定理由就无从审核（FR-052 AC-2）
        ai_reason=event.reason or "（无判定理由，属数据缺陷）",
        status=event.status,
        handled_by=handler.username if handler else None,
        handled_at=event.handled_at,
        created_at=event.created_at,
    )


@router.get("/events", response_model=Paged)
def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(PENDING|RELEASED|KEPT)$"),
    user_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
) -> Paged:
    rows, total = svc.list_events(db, page, page_size, status, user_id)
    return Paged(
        items=[_to_out(e, u, db).model_dump(mode="json") for e, u in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/events/{event_id}/handle", response_model=RiskEventOut)
def handle(
    event_id: int,
    payload: RiskHandleIn,
    db: Session = Depends(get_db),
    op: User = Depends(require_operator),
) -> RiskEventOut:
    event = svc.handle_event(db, event_id, payload.action, op)
    user = db.get(User, event.user_id)
    return _to_out(event, user, db)
