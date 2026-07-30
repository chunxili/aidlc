"""风控两层漏斗（FR-050/051/052）。

设计依据：ADR-005、ADR-007。

    规则层（纯 DB 计数，毫秒级）
      窗口计数 > hard_threshold          → BLOCK，**不调用 Bedrock**
      gray_low <= 计数 <= hard_threshold → 灰区，同步调一次 AI（2s，不重试）
      计数 < gray_low                    → PASS，不调用 Bedrock

SC-006（10 秒 50 次）由规则层拦截，全程零 Bedrock 调用，**断网亦可演示**。

"人工审核"的对象是**用户身上的风险标记**，不是一笔待批的领取（ADR-007，依据
需求原文"审核风控标记"）。被判 BLOCK 或 MANUAL_REVIEW 的请求直接失败，
不创建券、不占库存、不改 claimed_count。否则 claimed_count 将可减，同时破坏
INV-1 与 INV-3，并给攻击者一个免费的库存占用手段——风控本身沦为拒绝服务工具。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import risk_blocked, risk_manual_review
from ..models import RiskEvent, User, UserCoupon
from . import bedrock

PROMPT_VERSION = "risk-v1"


@dataclass
class Assessment:
    decision: str  # PASS / BLOCK / MANUAL_REVIEW
    decided_by: str  # RULE / AI
    score: int | None
    degraded: bool
    reason: str
    window_count: int
    ai_invocation_id: int | None = None


def window_count(db: Session, user_id: int) -> int:
    """窗口内的请求计数。

    **同时计入成功领取记录与已记录的风控事件**。只统计 user_coupons 会有个漏洞：
    用户被拦截后不产生券记录，计数便停止增长，连续攻击时会重新落回灰区甚至放行。
    这正是设计自检时发现的遗留项（database-design.md 第三节口径说明）。
    """
    settings = get_settings()
    since = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=settings.risk_window_seconds)

    claims = db.execute(
        select(func.count(UserCoupon.id)).where(
            UserCoupon.user_id == user_id, UserCoupon.claimed_at >= since
        )
    ).scalar_one()
    events = db.execute(
        select(func.count(RiskEvent.id)).where(
            RiskEvent.user_id == user_id, RiskEvent.created_at >= since
        )
    ).scalar_one()
    return claims + events


def _record(
    db: Session,
    user: User,
    campaign_id: int | None,
    assessment: Assessment,
) -> None:
    """落库风险标记并同步 users.risk_blocked。

    PASS 不落库：正常流量会把表打满，且无审核价值。
    """
    if assessment.decision == "PASS":
        return
    event = RiskEvent(
        user_id=user.id,
        campaign_id=campaign_id,
        window_request_count=assessment.window_count,
        risk_score=assessment.score,
        decision=assessment.decision,
        decided_by=assessment.decided_by,
        degraded=assessment.degraded,
        ai_invocation_id=assessment.ai_invocation_id,
        reason=assessment.reason,
        status="PENDING",
    )
    db.add(event)
    user.risk_blocked = True
    db.commit()


def assess(db: Session, user: User, campaign_id: int | None = None) -> Assessment:
    """领券前的风险评估。位于事务之外。"""
    settings = get_settings()

    if not settings.risk_enabled:
        return Assessment("PASS", "RULE", 0, False, "风控已关闭", 0)

    # 已有未解除的风险标记：直接拦截，无需重新评估。
    if user.risk_blocked:
        return Assessment(
            "MANUAL_REVIEW",
            "RULE",
            None,
            False,
            "该账号存在未解除的风险标记，需运营处理后方可领取",
            window_count(db, user.id),
        )

    count = window_count(db, user.id)

    # 规则层硬阈值：直接拦截，不调用 Bedrock。
    #
    # 边界取 >= 而非 >：灰区上界是 hard_threshold - 1。取 > 会留下 count ==
    # hard_threshold 这个既属灰区又未触发拦截的缝隙，实测中它导致灰区的保守判定
    # 抢先给出 MANUAL_REVIEW 并置 risk_blocked，使 BLOCK 分支永远走不到 ——
    # 50 次爆发式请求本该是硬拦截，却变成"需人工审核"，给运营制造噪音。
    if count >= settings.risk_hard_threshold:
        assessment = Assessment(
            "BLOCK",
            "RULE",
            100,
            False,
            (
                f"{settings.risk_window_seconds} 秒内请求 {count} 次，"
                f"超过硬阈值 {settings.risk_hard_threshold}，规则层直接拦截"
            ),
            count,
        )
        _record(db, user, campaign_id, assessment)
        return assessment

    # 低频：直接放行，不调用 Bedrock。
    if count < settings.risk_gray_low:
        return Assessment(
            "PASS", "RULE", min(count * 5, 40), False, f"窗口内请求 {count} 次，低频放行", count
        )

    # 灰区：同步调一次 AI。
    result = bedrock.assess_risk(
        db,
        user_id=user.id,
        features={
            "window_seconds": settings.risk_window_seconds,
            "window_request_count": count,
            "gray_low": settings.risk_gray_low,
            "hard_threshold": settings.risk_hard_threshold,
        },
        prompt_version=PROMPT_VERSION,
    )

    if result.ok and result.parsed is not None:
        score = int(result.parsed["score"])
        decision = result.parsed["decision"]
        assessment = Assessment(
            decision,
            "AI",
            score,
            False,
            str(result.parsed.get("reason") or "AI 未提供理由"),
            count,
            result.invocation_id,
        )
    else:
        # 降级为规则判定（FR-051）。
        #
        # 灰区降级时**放行**，理由：灰区的语义是"可疑但拿不准"，AI 不可用时并没有
        # 新增任何证据支持惩罚。而硬阈值在下一次请求即生效，最多漏判一次；
        # 反过来若降级就判 MANUAL_REVIEW，会对正常用户误伤并给运营制造待办噪音。
        # 宁可漏判一次，不误伤真实用户。
        assessment = Assessment(
            "PASS",
            "RULE",
            min(50 + count * 5, 95),
            True,
            (
                f"AI 不可用（{result.degrade_reason}），降级为规则判定：窗口内请求 "
                f"{count} 次，未达硬阈值 {settings.risk_hard_threshold}，放行"
            ),
            count,
            result.invocation_id,
        )

    _record(db, user, campaign_id, assessment)
    return assessment


def raise_if_denied(assessment: Assessment) -> None:
    """把评估结果转为 HTTP 错误。

    BLOCK 与 MANUAL_REVIEW 在当次请求结果上都是失败，区别在于：
    MANUAL_REVIEW 产生运营待办且文案不同；BLOCK 静默。
    """
    if assessment.decision == "BLOCK":
        raise risk_blocked()
    if assessment.decision == "MANUAL_REVIEW":
        raise risk_manual_review()


# ---------- 风险标记管理（FR-052）----------

def list_events(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    user_id: int | None = None,
) -> tuple[list[tuple[RiskEvent, User]], int]:
    stmt = (
        select(RiskEvent, User)
        .join(User, User.id == RiskEvent.user_id)
        .order_by(RiskEvent.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(RiskEvent.status == status_filter)
    if user_id:
        stmt = stmt.where(RiskEvent.user_id == user_id)
    rows = list(db.execute(stmt).all())
    total = len(rows)
    start = (page - 1) * page_size
    return [(r[0], r[1]) for r in rows[start : start + page_size]], total


def handle_event(db: Session, event_id: int, action: str, operator: User) -> RiskEvent:
    """运营处置风险标记。幂等：重复处理返回当前状态。

    RELEASE 解除后用户走**完全正常的领取路径**，系统不代为补发（ADR-007）。
    """
    from ..errors import risk_event_not_found

    event = db.get(RiskEvent, event_id)
    if event is None:
        raise risk_event_not_found()

    if event.status != "PENDING":
        return event  # 幂等

    event.status = "RELEASED" if action == "RELEASE" else "KEPT"
    event.handled_by = operator.id
    event.handled_at = dt.datetime.now(dt.UTC)

    if action == "RELEASE":
        target = db.get(User, event.user_id)
        # 该用户仍有其他待处理标记时不解除封禁。
        remaining = db.execute(
            select(func.count(RiskEvent.id)).where(
                RiskEvent.user_id == event.user_id,
                RiskEvent.status == "PENDING",
                RiskEvent.id != event.id,
            )
        ).scalar_one()
        if target is not None and remaining == 0:
            target.risk_blocked = False

    db.commit()
    db.refresh(event)
    return event
