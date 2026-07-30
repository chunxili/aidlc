#!/usr/bin/env python3
"""Bedrock 连通性与正常路径验收（DQ-003、FR-040、FR-050 的 AI 分支）。

此前所有 AI 测试走的都是 mock 或 not_configured 降级路径，正常路径一次未验证。
本脚本用真实凭证跑一次风控与推荐的 AI 分支，确认：
- Converse API 在该账号与区域下可用（DQ-003 结案）
- 服务端严格校验能接受合法输出
- ai_invocations 留痕正确且不含凭证

    cd src/backend && .venv\\Scripts\\python ..\\..\\scripts\\ai_connectivity_check.py

凭证从 src/backend/.env 读取，脚本不打印凭证任何片段。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services import bedrock  # noqa: E402

problems: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'[通过]' if ok else '[失败]'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        problems.append(label)


def main() -> int:
    settings = get_settings()
    print(f"region={settings.bedrock_region}  modelId={settings.bedrock_model_id}")
    print(f"凭证已配置: {settings.ai_configured}\n")
    if not settings.ai_configured:
        print("未配置 AWS_BEARER_TOKEN_BEDROCK，无法验证正常路径")
        return 1

    db = SessionLocal()
    try:
        # 与应用启动时一致地预热客户端：构造客户端逾 1 秒，不预热会让首个
        # 落入风控灰区的请求撞满 2 秒预算。
        print(f"0) 预热 Bedrock 客户端: {'成功' if bedrock.warm_up() else '失败'}")

        print("1) 裸调用 Converse")
        out, reason = bedrock._converse(
            '只输出 JSON，不要任何额外文字：{"ok": true}',
            settings.bedrock_recommend_timeout_seconds,
            settings.bedrock_recommend_max_retries,
        )
        check("Converse 调用成功", reason is None, f"degrade_reason={reason}")
        if reason is not None:
            print("\n   连通性失败，后续正常路径无法验证。")
            print("   若为 http_error，常见原因：凭证过期、模型访问未开通、区域不匹配。")
            return 1
        print(f"     模型返回（截断）: {str(out)[:120]}")

        print("\n2) 风控 AI 分支（灰区判定）")
        r = bedrock.assess_risk(
            db,
            user_id=None,
            features={
                "window_seconds": 10,
                "window_request_count": 7,
                "gray_low": 5,
                "hard_threshold": 10,
            },
            prompt_version="risk-v1",
        )
        check("风控 AI 返回通过严格校验", r.ok, f"degrade_reason={r.degrade_reason}")
        if r.ok and r.parsed:
            score, decision = r.parsed["score"], r.parsed["decision"]
            check("评分落在 0~100", isinstance(score, int) and 0 <= score <= 100, f"score={score}")
            check("决策为 PASS 或 MANUAL_REVIEW", decision in ("PASS", "MANUAL_REVIEW"), decision)
            check("理由非空", bool(str(r.parsed.get("reason", "")).strip()),
                  str(r.parsed.get("reason"))[:80])
        # 墙钟预算 = timeout × (重试次数 + 1) + 0.5s 开销
        budget_ms = int(
            (settings.bedrock_risk_timeout_seconds * (settings.bedrock_risk_max_retries + 1) + 0.5)
            * 1000
        )
        check(
            f"风控调用总耗时受墙钟截止约束（预算 {budget_ms} ms）",
            r.latency_ms <= budget_ms + 300,
            f"{r.latency_ms} ms",
        )

        print("\n3) 推荐 AI 分支（白名单约束）")
        candidates = {101: "餐饮满减", 102: "出行折扣", 103: "购物券"}
        features = {
            "claim_count": 5,
            "used_count": 3,
            "redeem_rate": 0.6,
            "category_preference": {"FOOD": 4, "TRAVEL": 1},
            "cold_start": False,
            "limit": 2,
            "candidates": "\n".join(
                f"- id={k}, 名称={v}, 品类=餐饮, 面额=20, 剩余=50" for k, v in candidates.items()
            ),
        }
        rec = bedrock.recommend(db, None, features, set(candidates), "recommend-v1")
        check("推荐 AI 返回通过严格校验", rec.ok, f"degrade_reason={rec.degrade_reason}")
        if rec.ok and rec.parsed:
            ids = [i["campaign_id"] for i in rec.parsed["items"]]
            check("返回的活动 id 全部落在候选白名单内", set(ids) <= set(candidates), str(ids))
            check("每项都有理由", all(str(i["reason"]).strip() for i in rec.parsed["items"]))
            for i in rec.parsed["items"]:
                print(f"     id={i['campaign_id']} 理由: {i['reason'][:70]}")

        print("\n4) 留痕与凭证安全")
        rows = db.execute(
            text(
                "SELECT purpose, degraded, degrade_reason, latency_ms, model_id"
                " FROM ai_invocations ORDER BY id DESC LIMIT 2"
            )
        ).all()
        check("最近两次调用均已留痕", len(rows) == 2, str(rows))
        check("正常路径的留痕 degraded=false", all(r[1] is False for r in rows), str([r[1] for r in rows]))
        leaked = db.execute(
            text(
                "SELECT count(*) FROM ai_invocations"
                " WHERE coalesce(raw_output,'') LIKE '%bedrock-api-key-%'"
                "    OR input_features::text LIKE '%bedrock-api-key-%'"
                "    OR input_features::text LIKE '%ASIA%'"
                "    OR coalesce(parsed_result::text,'') LIKE '%bedrock-api-key-%'"
            )
        ).scalar_one()
        check("留痕表中无凭证片段", leaked == 0, f"命中 {leaked} 行")

        print("\n" + "=" * 60)
        if problems:
            print(f"未通过 {len(problems)} 项：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("Bedrock 正常路径全部通过，DQ-003 结案：该账号与区域下模型可用")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
