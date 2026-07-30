"""统计口径（FR-030/031、ADR-008、NFR-009）。

SQL 直接照用 database-design.md 第三节的写法，不另起口径。

口径固定点：
- claim_rate 分母为 total_stock —— 系统无曝光埋点（CON-005），分母只能是库存
- redeem_rate 分母为 claimed_count —— 若取库存总量，低领取率活动的核销率永远
  趋近 0 且与领取率信息重复
- claimed_count = 0 时 redeem_rate 为 None，前端显示「—」，不得除零也不得返回 0

实时聚合，不建预聚合表、不加缓存：双写必然出现不一致，届时面板数字与数据库打架
是演示时最难解释的缺陷。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..errors import campaign_not_found
from ..schemas import CampaignStatsOut, IntegrityOut, OverviewOut

CLAIM_RATE_BASIS = "分母为库存总量（系统无曝光埋点，无法以曝光人数为分母）"
REDEEM_RATE_BASIS = "分母为已领取数（反映发出去的券有多少被真的使用）"

_CAMPAIGN_STATS_SQL = text(
    """
    SELECT c.id,
           c.name,
           c.total_stock,
           c.claimed_count,
           c.total_stock - c.claimed_count                                   AS remaining_stock,
           count(uc.id) FILTER (WHERE uc.status = 'USED')                    AS used_count,
           count(uc.id) FILTER (WHERE uc.status = 'UNUSED'
                                  AND uc.expires_at >  now())                AS active_count,
           count(uc.id) FILTER (WHERE uc.status = 'UNUSED'
                                  AND uc.expires_at <= now())                AS expired_count
      FROM campaigns c
      LEFT JOIN user_coupons uc ON uc.campaign_id = c.id
     WHERE c.id = :cid
     GROUP BY c.id
    """
)


def campaign_stats(db: Session, campaign_id: int) -> CampaignStatsOut:
    row = db.execute(_CAMPAIGN_STATS_SQL, {"cid": campaign_id}).one_or_none()
    if row is None:
        raise campaign_not_found()
    (
        cid,
        name,
        total_stock,
        claimed_count,
        remaining_stock,
        used_count,
        active_count,
        expired_count,
    ) = row

    return CampaignStatsOut(
        campaign_id=cid,
        campaign_name=name,
        total_stock=total_stock,
        claimed_count=claimed_count,
        remaining_stock=remaining_stock,
        used_count=used_count,
        active_count=active_count,
        expired_count=expired_count,
        claim_rate=round(claimed_count / total_stock, 4) if total_stock else 0.0,
        # claimed_count=0 时为 None，前端显示「—」（FR-030 AC-5）
        redeem_rate=round(used_count / claimed_count, 4) if claimed_count else None,
        claim_rate_basis=CLAIM_RATE_BASIS,
        redeem_rate_basis=REDEEM_RATE_BASIS,
    )


def overview(db: Session) -> OverviewOut:
    """全局汇总 + 异常指标（FR-031）。

    异常指标补齐需求二"管理员：监控异常"的落地：原需求 3.4 只列了三个指标，
    却赋予管理员监控异常的职责而无任何对应指标。
    """
    base = db.execute(
        text(
            "SELECT count(*), coalesce(sum(total_stock), 0), coalesce(sum(claimed_count), 0)"
            " FROM campaigns"
        )
    ).one()
    used = db.execute(
        text("SELECT count(*) FROM user_coupons WHERE status = 'USED'")
    ).scalar_one()
    blocked_24h = db.execute(
        text(
            "SELECT count(*) FROM risk_events"
            " WHERE decision IN ('BLOCK', 'MANUAL_REVIEW')"
            "   AND created_at >= now() - interval '24 hours'"
        )
    ).scalar_one()
    pending = db.execute(
        text("SELECT count(*) FROM risk_events WHERE status = 'PENDING'")
    ).scalar_one()

    return OverviewOut(
        campaign_count=base[0],
        total_stock=base[1],
        claimed_count=base[2],
        used_count=used,
        risk_blocked_24h=blocked_24h,
        risk_pending_count=pending,
    )


def integrity(db: Session) -> IntegrityOut:
    """对账自检：让不变量成为可点击的证据，而非只存在于文档里（NFR-009）。"""
    overflow = db.execute(
        text("SELECT count(*) FROM campaigns WHERE claimed_count > total_stock")
    ).scalar_one()
    mismatch = db.execute(
        text(
            "SELECT c.id FROM campaigns c"
            " LEFT JOIN user_coupons uc ON uc.campaign_id = c.id"
            " GROUP BY c.id, c.claimed_count"
            " HAVING count(uc.id) <> c.claimed_count"
        )
    ).scalars().all()
    return IntegrityOut(
        inv1_stock_overflow_count=overflow,
        inv2_mismatch_campaign_ids=list(mismatch),
        ok=(overflow == 0 and not mismatch),
    )
