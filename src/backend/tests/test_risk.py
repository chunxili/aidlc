"""T-08/T-09 验证：风控两层漏斗与风险标记闭环（FR-050/051/052、SC-006、SC-007）。"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text

from app.config import get_settings
from app.services import bedrock
from .conftest import auth_headers, create_campaign


def _claim(client, headers, cid):
    return client.post("/api/coupons/claim", json={"campaign_id": cid}, headers=headers)


def _reset_settings(**overrides):
    """改配置需清 lru_cache，否则改动不生效。"""
    get_settings.cache_clear()
    settings = get_settings()
    for k, v in overrides.items():
        object.__setattr__(settings, k, v)
    return settings


def test_high_frequency_blocked_by_rule_layer(client, op_headers, db, no_ai_credentials):
    """AC-1/AC-2：10 秒内 50 次领取，第 11 次被硬阈值拦截。

    **拦截决策由规则层独立作出**：该事件的 decided_by='RULE' 且 degraded=False，
    即拦截不依赖 AI 的可用性（ADR-005）。这是 SC-006 能在断网下演示的实质保证。

    需要说明的是：爆发式请求在计数上升过程中会**先穿过灰区** [gray_low,
    hard_threshold)，那几次请求确实会进入 AI 分支。无凭证时该分支在本地即短路
    （not_configured），不产生任何网络 I/O，随后降级放行。因此"零网络调用"成立，
    但"ai_invocations 表中零记录"不成立 —— 留痕是 FR-051 AC-3 明确要求的。

    本用例固定在**无凭证**（即断网等价）场景下断言，因此结果与 AI 可用性无关。
    AI 可用时灰区会给出真实判定，首次拦截可能提前到灰区内，那是另一条路径，
    由 test_gray_zone_calls_ai_and_can_manual_review 覆盖。
    """
    settings = get_settings()
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user190")

    responses = [_claim(client, headers, c["id"]) for _ in range(50)]
    statuses = [r.status_code for r in responses]

    assert statuses[0] == 201
    first_block = statuses.index(403)
    assert first_block == settings.risk_hard_threshold, (
        f"首次拦截发生在第 {first_block + 1} 次，硬阈值为 {settings.risk_hard_threshold}"
    )
    # 首次拦截必须是 BLOCK 而非 MANUAL_REVIEW：50 次爆发是明确的滥用，
    # 判成"需人工审核"会给运营制造噪音。
    assert responses[first_block].json()["code"] == "RISK_BLOCKED"

    block_event = db.execute(
        text(
            "SELECT decided_by, degraded FROM risk_events"
            " WHERE decision = 'BLOCK' ORDER BY id LIMIT 1"
        )
    ).one()
    assert block_event == ("RULE", False), "拦截决策不是由规则层独立作出的"

    # 灰区产生的 AI 调用在无凭证时全部本地短路，无网络 I/O
    reasons = db.execute(
        text("SELECT DISTINCT degrade_reason FROM ai_invocations")
    ).scalars().all()
    assert set(reasons) <= {"not_configured"}, f"出现了非本地短路的 AI 调用: {reasons}"


def test_block_leaves_stock_untouched(client, op_headers, db, no_ai_credentials):
    """AC-6：拦截前后 claimed_count 与券行数均无变化（ADR-007）。

    固定在无凭证下跑：配了真实凭证时，灰区每次调用要等满 2.5 秒的墙钟预算，
    30 次领取的总耗时会超过 10 秒的风控窗口，导致计数被重置、断言随机失败。
    本用例验的是规则层行为，与 AI 可用性无关。
    """
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user191")
    for _ in range(30):
        _claim(client, headers, c["id"])

    claimed = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    rows = db.execute(
        text("SELECT count(*) FROM user_coupons WHERE campaign_id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    assert claimed == rows, "库存扣减数与实际发券数不一致"
    # 被拦截的请求没有占用库存
    assert claimed <= get_settings().risk_hard_threshold + 1


def test_low_frequency_never_calls_ai(client, op_headers, user_a_headers, db):
    """AC-3：低频单次领取不调用 AI。"""
    c = create_campaign(client, op_headers, total_stock=10)
    r = _claim(client, user_a_headers, c["id"])
    assert r.status_code == 201
    assert r.json()["risk"]["decided_by"] == "RULE"
    assert db.execute(text("SELECT count(*) FROM ai_invocations")).scalar_one() == 0


def test_threshold_is_configurable(client, op_headers, db):
    """AC-4：阈值改为 3 后第 4 次即被拦截，无需改代码。"""
    original = get_settings().risk_hard_threshold
    try:
        _reset_settings(risk_hard_threshold=3, risk_gray_low=99)
        c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
        headers = auth_headers(client, "user192")
        statuses = [_claim(client, headers, c["id"]).status_code for _ in range(6)]
        assert statuses[:3] == [201, 201, 201], statuses
        assert statuses[3] == 403, f"阈值 3 时第 4 次应被拦截，实际 {statuses}"
    finally:
        _reset_settings(risk_hard_threshold=original, risk_gray_low=5)


def test_different_users_are_not_blocked(client, op_headers, db):
    """AC-5：N+1 个不同用户并发领取时无人被风控拦截（计数维度是 user_id）。"""
    c = create_campaign(client, op_headers, total_stock=30, per_user_limit=1)
    for i in range(1, 31):
        r = _claim(client, auth_headers(client, f"user{i:03d}"), c["id"])
        assert r.status_code == 201, f"user{i:03d} 被拦截: {r.json()}"
    events = db.execute(text("SELECT count(*) FROM risk_events")).scalar_one()
    assert events == 0, "不同用户各领一次却产生了风控事件"


def test_window_count_includes_risk_events(client, op_headers, db):
    """AC-7：连续被拦截时窗口计数持续生效，不会因不落 user_coupons 而回落。

    这是设计自检发现的遗留项：若只统计成功领取，被拦用户的计数会停止增长。
    """
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user193")
    for _ in range(20):
        _claim(client, headers, c["id"])
    # 后续请求必须持续被拒（不会因计数回落而放行）
    for _ in range(5):
        r = _claim(client, headers, c["id"])
        assert r.status_code == 403, "计数回落导致重新放行"


# ---------- 灰区 AI 与降级（FR-050 AI 层、FR-051）----------

def _fake_ai(score=90, decision="MANUAL_REVIEW", reason="AI 判定频次异常"):
    def _inner(db, user_id, features, prompt_version):
        return bedrock.AiResult(
            ok=True,
            parsed={"score": score, "decision": decision, "reason": reason},
            degrade_reason=None,
            invocation_id=None,
            latency_ms=120,
        )

    return _inner


def test_gray_zone_calls_ai_and_can_manual_review(client, op_headers, db):
    """灰区落入时调用 AI，AI 判 MANUAL_REVIEW 则当次领取失败并产生运营待办。"""
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user194")
    settings = get_settings()

    with patch.object(bedrock, "assess_risk", _fake_ai()):
        statuses = []
        for _ in range(settings.risk_gray_low + 1):
            statuses.append(_claim(client, headers, c["id"]).status_code)

    assert 403 in statuses, f"灰区未触发人工审核: {statuses}"
    events = db.execute(
        text("SELECT decision, decided_by FROM risk_events ORDER BY id DESC LIMIT 1")
    ).one()
    assert events == ("MANUAL_REVIEW", "AI")


def test_ai_failure_degrades_to_rule(client, op_headers, db):
    """FR-051：AI 不可用时降级为规则判定，领券功能不整体失败。"""

    def failing(db_, user_id, features, prompt_version):
        return bedrock.AiResult(
            ok=False,
            parsed=None,
            degrade_reason=bedrock.REASON_TIMEOUT,
            invocation_id=None,
            latency_ms=2000,
        )

    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user195")
    settings = get_settings()

    with patch.object(bedrock, "assess_risk", failing):
        results = [_claim(client, headers, c["id"]) for _ in range(settings.risk_gray_low + 2)]

    assert any(r.status_code == 201 for r in results), "降级后领券完全不可用"
    row = db.execute(
        text("SELECT degraded, decided_by FROM risk_events ORDER BY id DESC LIMIT 1")
    ).one_or_none()
    if row is not None:
        assert row[0] is True
        assert row[1] == "RULE", "降级后判定来源应为 RULE"


# ---------- 风险标记管理（FR-052、SC-007）----------

def test_risk_event_has_reason_for_review(client, op_headers, db):
    """AC-2：每条记录 ai_reason 非空 —— 否则运营无从审核。"""
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user196")
    for _ in range(get_settings().risk_hard_threshold + 3):
        _claim(client, headers, c["id"])

    r = client.get("/api/risk/events", headers=op_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "拦截后风险标记列表为空"
    for item in items:
        assert item["ai_reason"].strip(), "存在无判定理由的标记，运营无法审核"


def test_release_then_user_can_claim_again(client, op_headers, db):
    """AC-4：解除标记后该用户可成功领取（SC-007 闭环）。"""
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user197")
    for _ in range(get_settings().risk_hard_threshold + 3):
        _claim(client, headers, c["id"])
    assert _claim(client, headers, c["id"]).status_code == 403

    events = client.get("/api/risk/events?status=PENDING", headers=op_headers).json()["items"]
    for e in events:
        if e["username"] == "user197":
            client.post(f"/api/risk/events/{e['id']}/handle", json={"action": "RELEASE"},
                        headers=op_headers)

    # 清掉窗口内的历史记录以排除频次因素，仅验证标记解除的效果
    db.execute(text("DELETE FROM user_coupons WHERE user_id = (SELECT id FROM users WHERE username='user197')"))
    db.execute(text("DELETE FROM risk_events WHERE user_id = (SELECT id FROM users WHERE username='user197')"))
    db.commit()

    blocked = db.execute(
        text("SELECT risk_blocked FROM users WHERE username = 'user197'")
    ).scalar_one()
    assert blocked is False, "解除标记后 risk_blocked 未清除"
    assert _claim(client, headers, c["id"]).status_code == 201


def test_handle_is_idempotent(client, op_headers):
    """AC-5：重复处理同一标记返回当前状态，不报错。"""
    c = create_campaign(client, op_headers, total_stock=100, per_user_limit=100)
    headers = auth_headers(client, "user198")
    for _ in range(get_settings().risk_hard_threshold + 3):
        _claim(client, headers, c["id"])

    event_id = client.get("/api/risk/events", headers=op_headers).json()["items"][0]["id"]
    first = client.post(f"/api/risk/events/{event_id}/handle", json={"action": "KEEP"},
                        headers=op_headers)
    assert first.status_code == 200
    second = client.post(f"/api/risk/events/{event_id}/handle", json={"action": "RELEASE"},
                         headers=op_headers)
    assert second.status_code == 200
    assert second.json()["status"] == first.json()["status"], "重复处理改变了状态"


def test_no_approve_and_issue_endpoint(client, op_headers):
    """ADR-007：不存在"批准发券"接口。"""
    r = client.post("/api/risk/events/1/approve-issue", json={}, headers=op_headers)
    assert r.status_code in (404, 405)
