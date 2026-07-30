"""管理员人员名册与下钻的读模型（FR-069 ~ FR-071，CR-002）。

全部只读。管理员对人员的唯一写操作仍是审批，见 services/account.review（ADR-018）。

聚合口径（ADR-016）：名册的业绩数字实时聚合，不建汇总表。理由与 ADR-008 一致 ——
汇总表需要在每条写路径上维护，而这里没有任何写路径需要它。

**为什么用两个独立的 GROUP BY 子查询而不是一次 join**：
运营 → 活动是一对多，活动 → 券又是一对多。若把 campaigns 与 user_coupons 放进同一次
join 再聚合，活动行会被券行放大，`sum(total_stock)` 会按券数重复累加。分别聚合后
再各自 outerjoin 到 users，每个子查询对每个运营最多贡献一行，不存在放大。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BusinessError
from ..models import Campaign, Store, User, UserCoupon
from ..schemas import (
    OperatorBrief,
    OperatorCampaignOut,
    OperatorOut,
    RedemptionRecordOut,
    VerifierBrief,
)
from . import campaign as campaign_svc
from . import pricing

MAX_PAGE_SIZE = 100


def _paginate(page: int, page_size: int) -> tuple[int, int]:
    """把分页参数收敛到安全区间。

    上限存在的意义不是防御性编程：下钻列表的行数由业务数据决定，
    一个核销员可能有上万条核销记录，不设上限则单次请求可拖垮响应。
    """
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    return page, page_size


# ---------- 运营人员名册（FR-069）----------

def list_operators(db: Session) -> list[OperatorOut]:
    """全部运营人员及其投放业绩。含 PENDING 与 REJECTED（ADR-018）。"""
    # 子查询一：活动维度。claimed_count 直接取 campaigns 上的计数器，
    # 它与 user_coupons 的行数相等由 INV-2 保证，无须再数一遍券。
    by_campaign = (
        select(
            Campaign.created_by.label("operator_id"),
            func.count(Campaign.id).label("campaign_count"),
            func.coalesce(func.sum(Campaign.total_stock), 0).label("total_stock"),
            func.coalesce(func.sum(Campaign.claimed_count), 0).label("claimed_count"),
        )
        .where(Campaign.created_by.is_not(None))
        .group_by(Campaign.created_by)
        .subquery()
    )
    # 子查询二：券维度。只能从券表数，因为 campaigns 上没有核销计数器。
    by_coupon = (
        select(
            Campaign.created_by.label("operator_id"),
            func.count(UserCoupon.id).label("used_count"),
        )
        .join(Campaign, Campaign.id == UserCoupon.campaign_id)
        .where(UserCoupon.status == "USED", Campaign.created_by.is_not(None))
        .group_by(Campaign.created_by)
        .subquery()
    )

    stmt = (
        select(
            User,
            func.coalesce(by_campaign.c.campaign_count, 0),
            func.coalesce(by_campaign.c.total_stock, 0),
            func.coalesce(by_campaign.c.claimed_count, 0),
            func.coalesce(by_coupon.c.used_count, 0),
        )
        .outerjoin(by_campaign, by_campaign.c.operator_id == User.id)
        .outerjoin(by_coupon, by_coupon.c.operator_id == User.id)
        .where(User.role == "OPERATOR")
        .order_by(User.created_at, User.id)
    )

    result: list[OperatorOut] = []
    for user, campaign_count, total_stock, claimed_count, used_count in db.execute(stmt).all():
        result.append(
            OperatorOut(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                phone=user.phone,
                status=user.status,
                campaign_count=int(campaign_count),
                total_stock=int(total_stock),
                claimed_count=int(claimed_count),
                used_count=int(used_count),
                redeem_rate=(
                    round(int(used_count) / int(claimed_count), 4) if claimed_count else None
                ),
                created_at=user.created_at,
            )
        )
    return result


# ---------- 核销员的核销记录（FR-070）----------

def _require_user(db: Session, user_id: int, role: str, label: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.role != role:
        # 不区分「不存在」与「角色不符」：两者对管理员而言都是「这个 id 不是我要找的人」，
        # 分开报错只会让调用方多写一条分支。
        raise BusinessError(404, "USER_NOT_FOUND", f"{label}不存在")
    return user


def verifier_redemptions(
    db: Session, user_id: int, page: int = 1, page_size: int = 20
) -> tuple[VerifierBrief, list[RedemptionRecordOut], int, int, int]:
    page, page_size = _paginate(page, page_size)
    verifier = _require_user(db, user_id, "VERIFIER", "核销人员")
    store = db.get(Store, verifier.store_id) if verifier.store_id else None

    brief = VerifierBrief(
        id=verifier.id,
        username=verifier.username,
        display_name=verifier.display_name,
        phone=verifier.phone,
        # 门店对核销员非空由 CHECK 强制（ADR-015），此处的兜底只为类型完整
        store_name=store.name if store else "—",
        store_district=store.district if store else "—",
    )

    total = db.execute(
        select(func.count(UserCoupon.id)).where(
            UserCoupon.used_by == user_id, UserCoupon.status == "USED"
        )
    ).scalar_one()

    rows = db.execute(
        select(UserCoupon, Campaign, Store)
        .join(Campaign, Campaign.id == UserCoupon.campaign_id)
        .outerjoin(Store, Store.id == UserCoupon.used_store_id)
        .where(UserCoupon.used_by == user_id, UserCoupon.status == "USED")
        .order_by(UserCoupon.used_at.desc(), UserCoupon.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        RedemptionRecordOut(
            id=coupon.id,
            code=coupon.code,
            campaign_name=camp.name,
            coupon_type=camp.coupon_type,
            # 优惠描述取活动现值：它是「这是哪种券」的标识，不是账。
            # 金额才是账，必须用下面的快照（ADR-017）。
            benefit_text=pricing.describe(camp),
            order_amount=coupon.order_amount,
            discount_amount=coupon.discount_amount,
            payable_amount=(
                Decimal(coupon.order_amount) - Decimal(coupon.discount_amount)
                if coupon.order_amount is not None and coupon.discount_amount is not None
                else None
            ),
            used_at=coupon.used_at,
            store_name=store_row.name if store_row else None,
        )
        for coupon, camp, store_row in rows
    ]
    return brief, items, total, page, page_size


# ---------- 运营发布的活动（FR-071）----------

def operator_campaigns(
    db: Session, user_id: int, page: int = 1, page_size: int = 20
) -> tuple[OperatorBrief, list[OperatorCampaignOut], int, int, int]:
    page, page_size = _paginate(page, page_size)
    operator = _require_user(db, user_id, "OPERATOR", "运营人员")

    brief = OperatorBrief(
        id=operator.id,
        username=operator.username,
        display_name=operator.display_name,
        phone=operator.phone,
        status=operator.status,
    )

    total = db.execute(
        select(func.count(Campaign.id)).where(Campaign.created_by == user_id)
    ).scalar_one()

    campaigns = list(
        db.execute(
            select(Campaign)
            .where(Campaign.created_by == user_id)
            .order_by(Campaign.created_at.desc(), Campaign.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    if not campaigns:
        return brief, [], total, page, page_size

    # 只对本页的活动数核销量，不是整表扫描
    used_map = dict(
        db.execute(
            select(UserCoupon.campaign_id, func.count(UserCoupon.id))
            .where(
                UserCoupon.campaign_id.in_([c.id for c in campaigns]),
                UserCoupon.status == "USED",
            )
            .group_by(UserCoupon.campaign_id)
        ).all()
    )

    items = [
        OperatorCampaignOut(
            id=c.id,
            name=c.name,
            category=c.category,
            coupon_type=c.coupon_type,
            benefit_text=pricing.describe(c),
            total_stock=c.total_stock,
            claimed_count=c.claimed_count,
            used_count=int(used_map.get(c.id, 0)),
            remaining_stock=c.total_stock - c.claimed_count,
            # 状态派生，与 GET /api/campaigns 同一口径（ADR-002）
            status=campaign_svc.derive_status(c),
            start_at=c.start_at,
            end_at=c.end_at,
        )
        for c in campaigns
    ]
    return brief, items, total, page, page_size
