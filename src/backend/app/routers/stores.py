"""门店查询（FR-068）。公开接口：注册时需要选择门店，此时用户尚未登录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Store
from ..schemas import StoreOut
from ..store_data import DISTRICTS

router = APIRouter(prefix="/api/stores", tags=["门店"])


@router.get("", response_model=list[StoreOut])
def list_stores(
    district: str | None = Query(None), db: Session = Depends(get_db)
) -> list[StoreOut]:
    stmt = select(Store).where(Store.active.is_(True)).order_by(Store.district, Store.code)
    if district:
        stmt = stmt.where(Store.district == district)
    return [StoreOut.model_validate(s) for s in db.execute(stmt).scalars().all()]


@router.get("/districts", response_model=list[str])
def list_districts() -> list[str]:
    return DISTRICTS
