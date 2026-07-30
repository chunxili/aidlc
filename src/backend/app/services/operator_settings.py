"""运营设置、风控策略与配置审计（FR-007、FR-055、NFR-015）。

配置变更与审计日志在同一事务内提交；expected_version + 行锁避免运营人员互相覆盖。
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..errors import config_version_conflict, invalid_policy, operator_settings_not_found
from ..models import ConfigChangeLog, OperatorSettings, RiskPolicy, User
from ..schemas import (
    AlertSettings,
    AudienceThresholds,
    CustomRiskPolicyIn,
    OperatorSettingsOut,
    RiskPolicyOut,
)


def _policy_out(policy: RiskPolicy) -> RiskPolicyOut:
    return RiskPolicyOut(
        id=policy.id,
        name=policy.name,
        level=policy.level,
        hard_rules=policy.hard_rules,
        factor_weights=policy.factor_weights,
        review_threshold=policy.review_threshold,
        block_threshold=policy.block_threshold,
        version=policy.version,
    )


def _settings_row(db: Session, *, lock: bool = False) -> OperatorSettings:
    stmt = select(OperatorSettings).where(OperatorSettings.id == 1)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise operator_settings_not_found()
    return row


def _snapshot(settings: OperatorSettings, policy: RiskPolicy) -> dict:
    return {
        "version": settings.version,
        "audience_thresholds": settings.audience_thresholds,
        "default_risk_policy": _policy_out(policy).model_dump(mode="json"),
        "alert_settings": settings.alert_settings,
    }


def _to_out(db: Session, settings: OperatorSettings) -> OperatorSettingsOut:
    policy = db.get(RiskPolicy, settings.default_risk_policy_id)
    if policy is None:
        raise operator_settings_not_found()
    updater = db.get(User, settings.updated_by) if settings.updated_by else None
    return OperatorSettingsOut(
        version=settings.version,
        audience_thresholds=AudienceThresholds.model_validate(settings.audience_thresholds),
        default_risk_policy=_policy_out(policy),
        alert_settings=AlertSettings.model_validate(settings.alert_settings),
        updated_by=updater.username if updater else None,
        updated_at=settings.updated_at,
    )


def get(db: Session) -> OperatorSettingsOut:
    return _to_out(db, _settings_row(db))


def _begin_change(db: Session, expected_version: int) -> tuple[OperatorSettings, RiskPolicy, dict]:
    settings = _settings_row(db, lock=True)
    if settings.version != expected_version:
        raise config_version_conflict(settings.version)
    policy = db.get(RiskPolicy, settings.default_risk_policy_id)
    if policy is None:
        raise operator_settings_not_found()
    return settings, policy, _snapshot(settings, policy)


def _audit(
    db: Session,
    *,
    object_type: str,
    before: dict,
    after: dict,
    operator_id: int,
) -> None:
    db.add(
        ConfigChangeLog(
            object_type=object_type,
            object_id="1",
            action="UPDATE",
            before_data=before,
            after_data=after,
            changed_by=operator_id,
        )
    )


def _finish(
    db: Session,
    settings: OperatorSettings,
    policy: RiskPolicy,
    *,
    object_type: str,
    before: dict,
    operator_id: int,
) -> OperatorSettingsOut:
    settings.version += 1
    settings.updated_by = operator_id
    settings.updated_at = dt.datetime.now(dt.UTC)
    after = _snapshot(settings, policy)
    _audit(
        db,
        object_type=object_type,
        before=before,
        after=after,
        operator_id=operator_id,
    )
    db.commit()
    db.refresh(settings)
    return _to_out(db, settings)


def update_audiences(
    db: Session,
    *,
    expected_version: int,
    thresholds: AudienceThresholds,
    operator_id: int,
) -> OperatorSettingsOut:
    if thresholds.low_redeem_rate >= thresholds.high_redeem_rate:
        raise invalid_policy("低核销率阈值必须小于高核销率阈值")
    if thresholds.active_days >= thresholds.dormant_days:
        raise invalid_policy("活跃天数必须小于沉睡天数")
    settings, policy, before = _begin_change(db, expected_version)
    settings.audience_thresholds = thresholds.model_dump(mode="json")
    return _finish(
        db,
        settings,
        policy,
        object_type="OPERATOR_SETTINGS",
        before=before,
        operator_id=operator_id,
    )


def _validate_custom(custom: CustomRiskPolicyIn | None) -> CustomRiskPolicyIn:
    if custom is None:
        raise invalid_policy("选择 CUSTOM 时必须提供 custom 配置")
    if custom.review_threshold >= custom.block_threshold:
        raise invalid_policy("人工审核线必须小于拦截线")
    return custom


def update_risk(
    db: Session,
    *,
    expected_version: int,
    level: str,
    custom: CustomRiskPolicyIn | None,
    operator_id: int,
) -> OperatorSettingsOut:
    settings, old_policy, before = _begin_change(db, expected_version)

    if level == "CUSTOM":
        value = _validate_custom(custom)
        # 每次保存创建不可变策略版本，避免影响已引用该策略的活动。
        policy = RiskPolicy(
            name=f"{value.name[:40]}-{uuid.uuid4().hex[:12]}",
            level="CUSTOM",
            is_global_default=False,
            hard_rules=value.hard_rules.model_dump(mode="json"),
            factor_weights=value.factor_weights.model_dump(mode="json"),
            review_threshold=value.review_threshold,
            block_threshold=value.block_threshold,
            version=1,
            created_by=operator_id,
            updated_by=operator_id,
        )
        db.add(policy)
        db.flush()
    else:
        if custom is not None:
            raise invalid_policy("预设保护等级不接受 custom 配置")
        policy = db.execute(
            select(RiskPolicy).where(RiskPolicy.level == level).order_by(RiskPolicy.id)
        ).scalars().first()
        if policy is None:
            raise invalid_policy(f"保护等级 {level} 不存在")

    # partial unique index 要求先清旧默认，再设新默认。
    db.execute(update(RiskPolicy).where(RiskPolicy.is_global_default.is_(True)).values(is_global_default=False))
    db.flush()
    policy.is_global_default = True
    policy.updated_by = operator_id
    policy.updated_at = dt.datetime.now(dt.UTC)
    settings.default_risk_policy_id = policy.id
    return _finish(
        db,
        settings,
        policy,
        object_type="RISK_POLICY",
        before=before,
        operator_id=operator_id,
    )


def update_alerts(
    db: Session,
    *,
    expected_version: int,
    alerts: AlertSettings,
    operator_id: int,
) -> OperatorSettingsOut:
    settings, policy, before = _begin_change(db, expected_version)
    settings.alert_settings = alerts.model_dump(mode="json")
    return _finish(
        db,
        settings,
        policy,
        object_type="ALERT_SETTINGS",
        before=before,
        operator_id=operator_id,
    )


def list_changes(db: Session, page: int, page_size: int) -> tuple[list[tuple[ConfigChangeLog, User]], int]:
    base = select(ConfigChangeLog, User).join(User, User.id == ConfigChangeLog.changed_by)
    total = db.execute(select(func.count(ConfigChangeLog.id))).scalar_one()
    rows = list(
        db.execute(
            base.order_by(ConfigChangeLog.created_at.desc(), ConfigChangeLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return rows, total
