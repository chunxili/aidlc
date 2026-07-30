"""Bedrock Converse 封装与 AI 留痕（FR-042、FR-053）。

唯一接触外部网络、唯一持有凭证的模块（system-architecture.md 第二节）。
这条边界让 NFR-004「凭证不外泄」可以在单点审查。

固定顺序：构造请求 → 调用 → 解析 → **严格校验** → 写 ai_invocations → 返回或降级信号。

不依赖 Bedrock Structured Outputs 特性（ADR-009）：其模型与区域可用性无法在设计
阶段查证，把验收押在未验证的特性上是赌博。服务端校验是完全自主可控的。

鉴权：boto3 自动读取环境变量 AWS_BEARER_TOKEN_BEDROCK。
参考 https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html
以及 https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AiInvocation

log = logging.getLogger("coupon.bedrock")

# 模块级线程池，供墙钟截止使用。超时被放弃的任务会在后台自行结束，
# 不阻塞调用方（详见 _converse_with_deadline）。
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="bedrock")

# degrade_reason 的取值集合（database-design.md ai_invocations 一节）
REASON_NOT_CONFIGURED = "not_configured"
REASON_TIMEOUT = "timeout"
REASON_HTTP_ERROR = "http_error"
REASON_INVALID_JSON = "invalid_json"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_ID_NOT_IN_WHITELIST = "id_not_in_whitelist"
REASON_SCORE_OUT_OF_RANGE = "score_out_of_range"


@dataclass
class AiResult:
    ok: bool
    parsed: dict[str, Any] | None
    degrade_reason: str | None
    invocation_id: int | None
    latency_ms: int


def _log_invocation(
    db: Session,
    purpose: str,
    prompt_version: str,
    features: dict[str, Any],
    raw_output: str | None,
    parsed: dict[str, Any] | None,
    latency_ms: int,
    degrade_reason: str | None,
    user_id: int | None,
) -> int | None:
    """写留痕。失败不得阻断主业务，但要告警（FR-053）。

    不存完整 prompt：由 prompt_version + features 可完整重建。
    禁止写入凭证任何片段。
    """
    try:
        row = AiInvocation(
            purpose=purpose,
            model_id=get_settings().bedrock_model_id,
            prompt_version=prompt_version,
            input_features=features,
            raw_output=raw_output,
            parsed_result=parsed,
            latency_ms=latency_ms,
            degraded=degrade_reason is not None,
            degrade_reason=degrade_reason,
            user_id=user_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as exc:
        db.rollback()
        log.warning("AI 留痕写入失败（不阻断主业务）: %s", type(exc).__name__)
        return None


_CLIENT: Any = None
_CLIENT_LOCK = Lock()


def _get_client():
    """返回**单一共享**的 bedrock-runtime 客户端。

    两点代价都是实测出来的：

    1. 不缓存客户端：boto3 构造时要加载服务模型并新建 TLS 连接，实测每次 1 秒以上，
       直接吃掉风控 2 秒预算的大半，使灰区判定必然超时降级。
    2. 按 (超时, 重试) 分键缓存：风控与推荐各持一份客户端，各付一次冷启动。
       实测推荐（先调用）降到 1.4s，而风控作为该键的首次调用仍撞满 2.5s 预算。

    因此改为单一客户端，socket 层超时取较宽的值，**真正的按用途预算由
    _converse_with_deadline 的墙钟截止执行**。

    凭证必须在**创建客户端之前**注入环境变量：boto3 在构造时即解析凭证链，
    之后再改环境变量不生效。此处顺序颠倒曾使所有调用返回 http_error，
    并因异常详情被刻意吞掉而伪装成"模型不可用"。
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    from botocore.config import Config

    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        import boto3

        settings = get_settings()
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = settings.aws_bearer_token_bedrock
        widest = max(
            settings.bedrock_recommend_timeout_seconds, settings.bedrock_risk_timeout_seconds
        )
        _CLIENT = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            config=Config(
                connect_timeout=widest,
                read_timeout=widest,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        return _CLIENT


def reset_client() -> None:
    """丢弃缓存的客户端。更换凭证后调用，使新 token 生效。"""
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


def warm_up() -> bool:
    """预热客户端，让首个真实请求不必承担构造开销。

    在应用启动时调用。失败不影响启动（缺凭证时同样返回 False）。
    """
    settings = get_settings()
    if not settings.ai_configured:
        return False
    try:
        _get_client()
        return True
    except Exception as exc:
        log.warning("Bedrock 客户端预热失败: %s", type(exc).__name__)
        return False


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出中提取 JSON。

    模型常在 JSON 前后附带说明文字，直接 json.loads 会失败。先尝试整体解析，
    再退化为提取最外层花括号块。两者都失败则视为 invalid_json。
    """
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _converse(
    prompt: str, timeout: float, max_retries: int, max_tokens: int = 800
) -> tuple[str | None, str | None]:
    """调用 Converse，返回 (文本, 降级原因)。

    **总耗时受墙钟截止约束**，见 _converse_with_deadline。botocore 的 read_timeout
    只约束单次读取，不约束总耗时：实测风控调用配 read_timeout=2s 仍耗时 3.6s 并成功
    返回。风控位于领券这条交易链路上，3.6s 的阻塞正是 ADR-005 要避免的。

    换模型只改配置中的 modelId，请求与响应结构不变（ADR-009 选 Converse 的理由）。
    """
    from botocore.config import Config
    from botocore.exceptions import ClientError, ReadTimeoutError

    settings = get_settings()
    if not settings.ai_configured:
        return None, REASON_NOT_CONFIGURED

    try:
        client = _get_client()
        resp = client.converse(
            modelId=settings.bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            # maxTokens 直接决定延迟：实测同一 prompt 在 800/200/120 tokens 下
            # 分别耗时约 1820/1386/1015 ms。风控位于交易链路上，故用更小的上限。
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts), None
    except ReadTimeoutError:
        return None, REASON_TIMEOUT
    except ClientError:
        # 不记录异常详情：可能回显请求头（含凭证）。
        return None, REASON_HTTP_ERROR
    except Exception as exc:
        name = type(exc).__name__
        if "Timeout" in name:
            return None, REASON_TIMEOUT
        return None, REASON_HTTP_ERROR


def _converse_with_deadline(
    prompt: str, timeout: float, max_retries: int, max_tokens: int = 800
) -> tuple[str | None, str | None]:
    """给 _converse 套一层墙钟截止，保证总耗时不超过预算。

    为什么需要这层：botocore 的 read_timeout 按单次读取计算，不约束总耗时。
    实测风控（read_timeout=2s、不重试）仍会耗时 3.6s 并成功返回 —— 对领券这条
    交易链路而言，这个阻塞时长与"AI 不进交易链路"的设计意图相违。

    超时后工作线程可能仍在后台完成请求，但调用方已按降级路径继续，不受影响。
    预算按重试次数放大，与 botocore 自身的重试语义保持一致。
    """
    budget = timeout * (max_retries + 1) + 0.5  # 0.5s 留给 TLS 握手与序列化开销
    future = _POOL.submit(_converse, prompt, timeout, max_retries, max_tokens)
    try:
        return future.result(timeout=budget)
    except FuturesTimeout:
        # 刻意使用模块级共享线程池而非 with 语句：上下文管理器退出时会
        # shutdown(wait=True)，等待那个已被放弃的任务完成，把截止效果整个抵消掉
        # （实测预算 2.5s 却仍耗时 3.3s）。
        log.warning("Bedrock 调用超出墙钟预算 %.1fs，按超时降级", budget)
        return None, REASON_TIMEOUT


# ---------- 风控用途 ----------

RISK_PROMPT = """你是优惠券系统的风控引擎。根据用户在时间窗口内的领券请求频次评估风险。

窗口时长：{window_seconds} 秒
窗口内请求次数：{window_request_count}
灰区下界：{gray_low}
硬阈值：{hard_threshold}

请只输出 JSON，不要任何额外文字：
{{"score": <0-100 的整数>, "decision": "PASS" 或 "MANUAL_REVIEW", "reason": "<一句中文理由>"}}

判断准则：次数越接近硬阈值风险越高。风险高时 decision 取 MANUAL_REVIEW，否则 PASS。
reason 控制在 20 字以内。
"""

# 风控在交易链路上，输出上限压到 200：实测可把延迟从约 1.8s 降到 1.0s 上下，
# 稳定落在 2s 预算内。理由文本只需一句话，200 tokens 足够。
RISK_MAX_TOKENS = 200
RECOMMEND_MAX_TOKENS = 800


def assess_risk(
    db: Session, user_id: int, features: dict[str, Any], prompt_version: str
) -> AiResult:
    settings = get_settings()
    started = time.perf_counter()
    text, reason = _converse_with_deadline(
        RISK_PROMPT.format(**features),
        settings.bedrock_risk_timeout_seconds,
        settings.bedrock_risk_max_retries,
        max_tokens=RISK_MAX_TOKENS,
    )
    latency = int((time.perf_counter() - started) * 1000)

    parsed: dict[str, Any] | None = None
    if reason is None and text is not None:
        obj = _extract_json(text)
        if obj is None:
            reason = REASON_INVALID_JSON
        elif not {"score", "decision"} <= obj.keys():
            reason = REASON_SCHEMA_INVALID
        elif obj["decision"] not in ("PASS", "MANUAL_REVIEW"):
            reason = REASON_SCHEMA_INVALID
        else:
            try:
                score = int(obj["score"])
            except (TypeError, ValueError):
                reason = REASON_SCORE_OUT_OF_RANGE
            else:
                if not 0 <= score <= 100:
                    reason = REASON_SCORE_OUT_OF_RANGE
                else:
                    parsed = {
                        "score": score,
                        "decision": obj["decision"],
                        "reason": obj.get("reason", ""),
                    }

    invocation_id = _log_invocation(
        db, "RISK", prompt_version, features, text, parsed, latency, reason, user_id
    )
    return AiResult(reason is None and parsed is not None, parsed, reason, invocation_id, latency)


# ---------- 推荐用途 ----------

RECOMMEND_PROMPT = """你是优惠券推荐引擎。从候选活动中挑选最适合该用户的若干个并给出理由。

用户画像：
- 历史领券次数：{claim_count}
- 历史核销次数：{used_count}
- 核销率：{redeem_rate}
- 偏好品类分布：{category_preference}
- 是否新用户（无历史行为）：{cold_start}

候选活动（**只能从这些 id 中挑选，禁止编造**）：
{candidates}

请只输出 JSON，不要任何额外文字，最多 {limit} 项，按推荐优先级排序：
{{"items": [{{"campaign_id": <候选中的 id>, "reason": "<一句中文推荐理由，需结合用户画像与活动品类>"}}]}}
"""


def recommend(
    db: Session,
    user_id: int,
    features: dict[str, Any],
    candidate_ids: set[int],
    prompt_version: str,
) -> AiResult:
    """调用 AI 重排候选集。

    返回后**逐个校验 id 在候选白名单内**（ADR-009）：AI 只能重排给定集合，
    不能凭空造活动。幻觉出的活动会让用户点进去 404，是演示级风险。
    """
    settings = get_settings()
    started = time.perf_counter()
    text, reason = _converse_with_deadline(
        RECOMMEND_PROMPT.format(**features),
        settings.bedrock_recommend_timeout_seconds,
        settings.bedrock_recommend_max_retries,
        max_tokens=RECOMMEND_MAX_TOKENS,
    )
    latency = int((time.perf_counter() - started) * 1000)

    parsed: dict[str, Any] | None = None
    if reason is None and text is not None:
        obj = _extract_json(text)
        if obj is None:
            reason = REASON_INVALID_JSON
        elif not isinstance(obj.get("items"), list):
            reason = REASON_SCHEMA_INVALID
        else:
            kept: list[dict[str, Any]] = []
            dropped = 0
            for item in obj["items"]:
                if not isinstance(item, dict) or "campaign_id" not in item:
                    dropped += 1
                    continue
                try:
                    cid = int(item["campaign_id"])
                except (TypeError, ValueError):
                    dropped += 1
                    continue
                if cid not in candidate_ids:
                    # 白名单外的 id 直接丢弃，不进入响应。
                    dropped += 1
                    continue
                kept.append({"campaign_id": cid, "reason": str(item.get("reason") or "").strip()})
            if not kept:
                # 全部落在白名单外：视为不可用，走降级而不是返回空列表，
                # 因为"列表非空"是硬保证（FR-041）。
                reason = REASON_ID_NOT_IN_WHITELIST
            else:
                parsed = {"items": kept, "dropped": dropped}

    invocation_id = _log_invocation(
        db, "RECOMMEND", prompt_version, features, text, parsed, latency, reason, user_id
    )
    return AiResult(reason is None and parsed is not None, parsed, reason, invocation_id, latency)


# ---------- 按需求推荐用途 ----------

RECOMMEND_BY_NEED_PROMPT = """你是优惠券推荐引擎。用户用一句话描述了他的需求，请理解需求，并从候选活动中挑选最匹配的若干个，逐一说明为何匹配。

用户需求（用户原话）：{need}

用户画像（辅助参考，不要凌驾于需求之上）：
- 历史领券次数：{claim_count}
- 历史核销次数：{used_count}
- 偏好品类分布：{category_preference}
- 是否新用户（无历史行为）：{cold_start}

候选活动（**只能从这些 id 中挑选，禁止编造**）：
{candidates}

请只输出 JSON，不要任何额外文字。items 最多 {limit} 项，按与需求的匹配度从高到低排序；
analysis 用一句中文概述你对用户需求的理解：
{{"analysis": "<一句中文，概述理解到的需求>", "items": [{{"campaign_id": <候选中的 id>, "reason": "<一句中文理由，说明为何匹配该需求>"}}]}}
"""

RECOMMEND_BY_NEED_MAX_TOKENS = 900


def recommend_by_need(
    db: Session,
    user_id: int,
    features: dict[str, Any],
    candidate_ids: set[int],
    prompt_version: str,
) -> AiResult:
    """按用户自述需求调用 AI 匹配候选集。

    与 recommend() 同样做**逐个 id 白名单校验**，并额外解析 analysis（AI 对需求的理解）。
    """
    settings = get_settings()
    started = time.perf_counter()
    text, reason = _converse_with_deadline(
        RECOMMEND_BY_NEED_PROMPT.format(**features),
        settings.bedrock_recommend_timeout_seconds,
        settings.bedrock_recommend_max_retries,
        max_tokens=RECOMMEND_BY_NEED_MAX_TOKENS,
    )
    latency = int((time.perf_counter() - started) * 1000)

    parsed: dict[str, Any] | None = None
    if reason is None and text is not None:
        obj = _extract_json(text)
        if obj is None:
            reason = REASON_INVALID_JSON
        elif not isinstance(obj.get("items"), list):
            reason = REASON_SCHEMA_INVALID
        else:
            kept: list[dict[str, Any]] = []
            dropped = 0
            for item in obj["items"]:
                if not isinstance(item, dict) or "campaign_id" not in item:
                    dropped += 1
                    continue
                try:
                    cid = int(item["campaign_id"])
                except (TypeError, ValueError):
                    dropped += 1
                    continue
                if cid not in candidate_ids:
                    dropped += 1
                    continue
                kept.append({"campaign_id": cid, "reason": str(item.get("reason") or "").strip()})
            if not kept:
                reason = REASON_ID_NOT_IN_WHITELIST
            else:
                parsed = {
                    "items": kept,
                    "dropped": dropped,
                    "analysis": str(obj.get("analysis") or "").strip(),
                }

    invocation_id = _log_invocation(
        db, "RECOMMEND", prompt_version, features, text, parsed, latency, reason, user_id
    )
    return AiResult(reason is None and parsed is not None, parsed, reason, invocation_id, latency)
