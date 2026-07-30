"""核销路由。仅核销人员可执行（D-12）。

项目已排除支付结算，用户自助核销属纯自毁操作，无业务意义；核销之所以存在，
是因为线下有人验券。竞赛演示步骤 d/e 写"用户 A 核销"，实际由核销员执行，
用户仅出示券码 —— 演示时需主动说明。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import RedeemCheckOut, RedeemIn, RedeemOut
from ..security import require_verifier
from ..services import redeem as svc

router = APIRouter(prefix="/api/redemptions", tags=["核销"])


@router.post("", response_model=RedeemOut)
def redeem(
    payload: RedeemIn,
    db: Session = Depends(get_db),
    verifier: User = Depends(require_verifier),
) -> RedeemOut:
    return RedeemOut(**svc.redeem(db, payload.code.strip().upper(), verifier))


@router.get("/{code}", response_model=RedeemCheckOut)
def check(
    code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_verifier),
) -> RedeemCheckOut:
    return RedeemCheckOut(**svc.check(db, code.strip().upper()))
