"""AI 推荐路由。

**独立只读接口，不在领券路径上**（ADR-005）。推荐发生在用户决策之前，
这也是竞赛演示步骤 b「领取成功含 AI 推荐理由」的实现方式：
理由在页面上已存在，而非来自领券响应。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import RecommendationOut
from ..security import require_user
from ..services import recommend as svc

router = APIRouter(prefix="/api/recommendations", tags=["AI 推荐"])


@router.get("", response_model=RecommendationOut)
def recommendations(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> RecommendationOut:
    return svc.recommend(db, user.id, limit)
