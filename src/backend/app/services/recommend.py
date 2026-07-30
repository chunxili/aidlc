"""AI 智能推券（FR-040/041）。

流程（ADR-005、ADR-009）：
1. **确定性 SQL 召回**候选集：进行中 + 有库存 + 该用户未领满
2. 构造用户特征（仅来自领券与核销记录 —— 系统无订单与支付数据，CON-006）
3. 调用 Bedrock 重排并生成理由
4. **逐个校验返回的 id 在候选白名单内，不在的丢弃**
5. 任一环节失败 → 降级为热度排序 + 模板理由

"列表非空"是**硬保证**，由降级路径兜底，不依赖 AI 可用性（FR-041）。
本接口是独立只读接口，不在领券路径上。
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Campaign, UserCoupon
from ..schemas import RecommendationItem, RecommendationOut
from . import bedrock
from .campaign import list_available_for_user

PROMPT_VERSION = "recommend-v1"

CATEGORY_LABEL = {
    "FOOD": "餐饮",
    "TRAVEL": "出行",
    "SHOPPING": "购物",
    "LIFE": "生活服务",
}


def _user_features(db: Session, user_id: int) -> dict:
    """用户画像。数据源仅有领券与核销记录（CON-006）。"""
    rows = db.execute(
        select(Campaign.category, UserCoupon.status)
        .join(Campaign, Campaign.id == UserCoupon.campaign_id)
        .where(UserCoupon.user_id == user_id)
    ).all()
    claim_count = len(rows)
    used_count = sum(1 for _, s in rows if s == "USED")
    pref = Counter(cat for cat, _ in rows)
    return {
        "claim_count": claim_count,
        "used_count": used_count,
        "redeem_rate": round(used_count / claim_count, 2) if claim_count else 0.0,
        "category_preference": dict(pref) or "无",
        "cold_start": claim_count == 0,
    }


def _popularity(db: Session, campaign_ids: list[int]) -> dict[int, float]:
    """热度 = 领取率。冷启动与降级路径的排序依据。"""
    rows = db.execute(
        select(Campaign.id, Campaign.claimed_count, Campaign.total_stock).where(
            Campaign.id.in_(campaign_ids)
        )
    ).all()
    return {cid: (claimed / total if total else 0.0) for cid, claimed, total in rows}


def _template_reason(c: Campaign, cold_start: bool) -> str:
    label = CATEGORY_LABEL.get(c.category, c.category)
    if cold_start:
        return f"新用户推荐：{label}类高性价比券，面额 {c.face_value} 元，先领先用"
    return f"{label}类热门券，面额 {c.face_value} 元，当前剩余 {c.total_stock - c.claimed_count} 张"


def recommend(db: Session, user_id: int, limit: int | None = None) -> RecommendationOut:
    settings = get_settings()
    limit = limit or settings.recommend_result_limit

    # 1. 确定性召回
    available = list_available_for_user(db, user_id)[: settings.recommend_candidate_limit]
    if not available:
        # 候选集本身为空属合法状态，不是错误（FR-040 异常处理）
        return RecommendationOut(items=[], degraded=False, degrade_reason=None, cold_start=False)

    by_id = {c.id: c for c, _ in available}
    features = _user_features(db, user_id)
    cold_start = bool(features["cold_start"])

    # 2~4. 调 AI 重排并做白名单校验
    payload = dict(features)
    payload["limit"] = limit
    payload["candidates"] = "\n".join(
        f"- id={c.id}, 名称={c.name}, 品类={CATEGORY_LABEL.get(c.category, c.category)},"
        f" 面额={c.face_value}, 剩余={c.total_stock - c.claimed_count}"
        for c in by_id.values()
    )
    result = bedrock.recommend(db, user_id, payload, set(by_id), PROMPT_VERSION)

    if result.ok and result.parsed:
        # 白名单校验在此**再做一次**。bedrock 层已经过滤过，这里不是冗余：
        # 白名单是正确性保证，不应依赖单一层次。若 bedrock 层被改动、被 mock 或
        # 换了实现，本层仍能挡住幻觉出的活动 id，避免用户点进去 404。
        items = [
            RecommendationItem(
                campaign_id=cid,
                campaign_name=by_id[cid].name,
                category=by_id[cid].category,
                face_value=by_id[cid].face_value,
                remaining_stock=by_id[cid].total_stock - by_id[cid].claimed_count,
                reason=it.get("reason") or _template_reason(by_id[cid], cold_start),
            )
            for it in result.parsed["items"]
            if (cid := it.get("campaign_id")) in by_id
        ][:limit]
        if items:
            return RecommendationOut(
                items=items, degraded=False, degrade_reason=None, cold_start=cold_start
            )
        # AI 返回的全部 id 都不在候选集内：走降级而不是返回空列表，
        # 因为"列表非空"是硬保证（FR-041）。
        result = bedrock.AiResult(
            False, None, bedrock.REASON_ID_NOT_IN_WHITELIST, result.invocation_id, result.latency_ms
        )

    # 5. 降级：热度排序 + 模板理由。列表非空是硬保证。
    pop = _popularity(db, list(by_id))
    ordered = sorted(by_id.values(), key=lambda c: pop.get(c.id, 0.0), reverse=True)[:limit]
    return RecommendationOut(
        items=[
            RecommendationItem(
                campaign_id=c.id,
                campaign_name=c.name,
                category=c.category,
                face_value=c.face_value,
                remaining_stock=c.total_stock - c.claimed_count,
                reason=_template_reason(c, cold_start),
            )
            for c in ordered
        ],
        degraded=True,
        degrade_reason=result.degrade_reason,
        cold_start=cold_start,
    )
