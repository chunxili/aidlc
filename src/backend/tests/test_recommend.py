"""T-07/T-11 验证：AI 推荐、白名单校验与降级（FR-040/041/042/053、SC-005）。"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text

from app.services import bedrock
from .conftest import auth_headers, create_campaign


def _ai(items, ok=True, reason=None):
    def _inner(db, user_id, features, candidate_ids, prompt_version):
        return bedrock.AiResult(
            ok=ok,
            parsed={"items": items, "dropped": 0} if ok else None,
            degrade_reason=reason,
            invocation_id=None,
            latency_ms=100,
        )

    return _inner


def test_no_credentials_still_returns_non_empty(
    client, op_headers, user_a_headers, db, no_ai_credentials
):
    """AC-5：无凭证下仍返回非空列表且 degraded=true（列表非空是硬保证）。"""
    create_campaign(client, op_headers, name="餐饮券", total_stock=10)
    create_campaign(client, op_headers, name="出行券", category="TRAVEL", total_stock=10)

    r = client.get("/api/recommendations", headers=user_a_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"], "无凭证时推荐列表为空，违背硬保证"
    assert body["degraded"] is True
    assert body["degrade_reason"] == "not_configured"
    for item in body["items"]:
        assert item["reason"].strip(), "存在空理由"


def test_cold_start_flag_and_non_empty(client, op_headers, db):
    """AC-4：零历史用户仍返回非空且 cold_start=true。"""
    create_campaign(client, op_headers, total_stock=10)
    r = client.get("/api/recommendations", headers=auth_headers(client, "user150"))
    body = r.json()
    assert body["cold_start"] is True
    assert body["items"]


def test_ai_reorder_is_respected(client, op_headers, user_a_headers, db):
    """AI 可用时按其排序返回，理由取自 AI。"""
    c1 = create_campaign(client, op_headers, name="A券", total_stock=10)
    c2 = create_campaign(client, op_headers, name="B券", total_stock=10)

    fake = _ai([
        {"campaign_id": c2["id"], "reason": "你偏好该品类"},
        {"campaign_id": c1["id"], "reason": "面额较高"},
    ])
    with patch.object(bedrock, "recommend", fake):
        body = client.get("/api/recommendations", headers=user_a_headers).json()

    assert body["degraded"] is False
    assert [i["campaign_id"] for i in body["items"]] == [c2["id"], c1["id"]]
    assert body["items"][0]["reason"] == "你偏好该品类"


def test_hallucinated_id_is_dropped(client, op_headers, user_a_headers, db):
    """AC-2：AI 返回白名单外的 id 时该项被丢弃，不出现在响应。

    幻觉出的活动会让用户点进去 404，是演示级风险（ADR-009）。
    """
    c1 = create_campaign(client, op_headers, name="真实券", total_stock=10)
    fake = _ai([
        {"campaign_id": 999999, "reason": "编造的活动"},
        {"campaign_id": c1["id"], "reason": "真实活动"},
    ])
    with patch.object(bedrock, "recommend", fake):
        body = client.get("/api/recommendations", headers=user_a_headers).json()

    ids = [i["campaign_id"] for i in body["items"]]
    assert 999999 not in ids, "幻觉 id 进入了响应"
    assert c1["id"] in ids


def test_all_ids_hallucinated_falls_back(client, op_headers, user_a_headers, db):
    """全部 id 落在白名单外时走降级，而不是返回空列表。"""
    create_campaign(client, op_headers, total_stock=10)
    with patch.object(bedrock, "recommend", _ai([], ok=False, reason="id_not_in_whitelist")):
        body = client.get("/api/recommendations", headers=user_a_headers).json()
    assert body["items"], "应降级兜底而非返回空列表"
    assert body["degraded"] is True


def test_soldout_expired_and_maxed_never_appear(client, op_headers, user_a_headers, db):
    """AC-3：售罄、已过期、已领满的活动永不出现。"""
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    ok = create_campaign(client, op_headers, name="可领", total_stock=10)
    soldout = create_campaign(client, op_headers, name="售罄", total_stock=1)
    ended = create_campaign(
        client,
        op_headers,
        name="已结束",
        start_at=(now - dt.timedelta(days=2)).isoformat(),
        end_at=(now - dt.timedelta(days=1)).isoformat(),
    )
    maxed = create_campaign(client, op_headers, name="已领满", total_stock=10, per_user_limit=1)

    db.execute(
        text("UPDATE campaigns SET claimed_count = total_stock WHERE id = :cid"),
        {"cid": soldout["id"]},
    )
    db.commit()
    client.post("/api/coupons/claim", json={"campaign_id": maxed["id"]}, headers=user_a_headers)

    body = client.get("/api/recommendations", headers=user_a_headers).json()
    ids = {i["campaign_id"] for i in body["items"]}
    assert ok["id"] in ids
    for bad, label in [(soldout, "售罄"), (ended, "已结束"), (maxed, "已领满")]:
        assert bad["id"] not in ids, f"{label}活动出现在推荐中"


def test_recommend_is_read_only(client, op_headers, user_a_headers, db):
    """AC-7：调用前后库存与券状态无任何变化。"""
    c = create_campaign(client, op_headers, total_stock=10)
    before = db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one()
    rows_before = db.execute(text("SELECT count(*) FROM user_coupons")).scalar_one()

    client.get("/api/recommendations", headers=user_a_headers)

    assert db.execute(
        text("SELECT claimed_count FROM campaigns WHERE id = :cid"), {"cid": c["id"]}
    ).scalar_one() == before
    assert db.execute(text("SELECT count(*) FROM user_coupons")).scalar_one() == rows_before


def test_empty_candidate_set_returns_empty_list(client, user_a_headers):
    """候选集为空属合法状态，不是错误。"""
    r = client.get("/api/recommendations", headers=user_a_headers)
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["degraded"] is False


def test_degradation_is_logged(client, op_headers, user_a_headers, db, no_ai_credentials):
    """AC-8/FR-053：降级发生时 ai_invocations 留有记录且原因非空。"""
    create_campaign(client, op_headers, total_stock=10)
    client.get("/api/recommendations", headers=user_a_headers)
    row = db.execute(
        text(
            "SELECT purpose, degraded, degrade_reason, latency_ms FROM ai_invocations"
            " ORDER BY id DESC LIMIT 1"
        )
    ).one_or_none()
    assert row is not None, "降级未留痕"
    assert row[0] == "RECOMMEND"
    assert row[1] is True
    assert row[2], "degrade_reason 为空"


def test_no_credential_leak_in_ai_log(client, op_headers, user_a_headers, db):
    """AC-7（FR-053）：留痕表中不得出现凭证特征串（NFR-004）。"""
    create_campaign(client, op_headers, total_stock=10)
    client.get("/api/recommendations", headers=user_a_headers)
    leaked = db.execute(
        text(
            "SELECT count(*) FROM ai_invocations"
            " WHERE coalesce(raw_output, '') LIKE '%bedrock-api-key-%'"
            "    OR input_features::text LIKE '%ASIA%'"
            "    OR input_features::text LIKE '%bedrock-api-key-%'"
        )
    ).scalar_one()
    assert leaked == 0


# ---------- T-07 Bedrock 封装的输出校验 ----------

def test_extract_json_tolerates_surrounding_text():
    """模型常在 JSON 前后附说明文字，需能提取。"""
    assert bedrock._extract_json('好的，结果如下：{"score": 10} 完毕') == {"score": 10}
    assert bedrock._extract_json("完全不是 JSON") is None


def test_score_out_of_range_is_rejected(db):
    """AC-3（T-07）：评分 150 判为非法，degrade_reason=score_out_of_range。"""
    with patch.object(
        bedrock, "_converse", lambda *a, **k: ('{"score": 150, "decision": "PASS"}', None)
    ):
        result = bedrock.assess_risk(db, user_id=None, features={
            "window_seconds": 10, "window_request_count": 6, "gray_low": 5, "hard_threshold": 10
        }, prompt_version="t")
    assert result.ok is False
    assert result.degrade_reason == bedrock.REASON_SCORE_OUT_OF_RANGE


def test_invalid_json_is_rejected(db):
    """AC-2（T-07）：非法 JSON 不抛未捕获异常，转为降级信号。"""
    with patch.object(bedrock, "_converse", lambda *a, **k: ("这不是 JSON", None)):
        result = bedrock.assess_risk(db, user_id=None, features={
            "window_seconds": 10, "window_request_count": 6, "gray_low": 5, "hard_threshold": 10
        }, prompt_version="t")
    assert result.ok is False
    assert result.degrade_reason == bedrock.REASON_INVALID_JSON


def test_bad_decision_value_is_rejected(db):
    with patch.object(
        bedrock, "_converse", lambda *a, **k: ('{"score": 10, "decision": "YOLO"}', None)
    ):
        result = bedrock.assess_risk(db, user_id=None, features={
            "window_seconds": 10, "window_request_count": 6, "gray_low": 5, "hard_threshold": 10
        }, prompt_version="t")
    assert result.degrade_reason == bedrock.REASON_SCHEMA_INVALID


def test_model_id_switch_needs_no_code_change(db):
    """AC-1（T-07）：仅改配置即可换模型。"""
    from app.config import get_settings

    settings = get_settings()
    original = settings.bedrock_model_id
    try:
        object.__setattr__(settings, "bedrock_model_id", "another.model.v1")
        with patch.object(
            bedrock, "_converse", lambda *a, **k: ('{"score": 10, "decision": "PASS"}', None)
        ):
            bedrock.assess_risk(db, user_id=None, features={
                "window_seconds": 10, "window_request_count": 6, "gray_low": 5,
                "hard_threshold": 10
            }, prompt_version="t")
        logged = db.execute(
            text("SELECT model_id FROM ai_invocations ORDER BY id DESC LIMIT 1")
        ).scalar_one()
        assert logged == "another.model.v1"
    finally:
        object.__setattr__(settings, "bedrock_model_id", original)


def test_not_configured_makes_no_network_call(db, no_ai_credentials):
    """AC-6（T-07）：未配置凭证时不发起网络请求，且留痕 not_configured。"""
    text_out, reason = bedrock._converse("prompt", 1.0, 0)
    assert text_out is None
    assert reason == bedrock.REASON_NOT_CONFIGURED
