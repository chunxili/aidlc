"""全局配置：单一配置来源。

设计依据：
- system-architecture.md 第五节「配置边界」：全部可变参数集中于单一 Settings 对象。
- NFR-004：Bedrock 凭证只从环境变量读取，禁止硬编码，禁止写入日志与响应。
- FR-050 AC-4：风控阈值必须可配，演示现场可调而无需改代码。
- FR-042：modelId / region / 超时分级可配，换模型不改业务代码。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 数据库（CON-004）----
    # 并发正确性依赖条件 UPDATE + 唯一索引，由 PostgreSQL 的行级锁与唯一约束保证，
    # 应用层不实现任何锁（ADR-001）。
    database_url: str = "postgresql+psycopg://coupon:coupon@localhost:5432/coupon"

    # ---- 认证（FR-060）----
    # 默认值仅供本地开发；部署时必须由环境变量覆盖（NFR-004）。
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # ---- Mock 用户 seed（FR-062）----
    # FR-010 AC-1 要求 N+1 个不同用户并发领取，故需批量用户。
    seed_normal_user_count: int = 200

    # ---- 风控（FR-050，三个阈值均可配）----
    risk_window_seconds: int = 10
    risk_hard_threshold: int = 10  # 窗口内计数 > 该值 → 直接拦截，不调用 AI
    risk_gray_low: int = 5  # 落入 [gray_low, hard_threshold] → 灰区，调用一次 AI
    risk_enabled: bool = True

    # ---- Bedrock（FR-042 / CON-002）----
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
    # 短期 API key，有效期 12 小时。过期后替换环境变量并重启即生效，系统不自动续期。
    aws_bearer_token_bedrock: str = ""
    # 超时分级：风控位于领券这条交易链路上，宁可降级也不拖延。
    bedrock_recommend_timeout_seconds: float = 3.0
    bedrock_recommend_max_retries: int = 1
    bedrock_risk_timeout_seconds: float = 2.0
    bedrock_risk_max_retries: int = 0

    # ---- 推荐（FR-040）----
    recommend_candidate_limit: int = 20
    recommend_result_limit: int = 5

    @property
    def ai_configured(self) -> bool:
        """凭证缺失时服务仍须正常启动，AI 功能进入降级模式（FR-071 AC-2）。"""
        return bool(self.aws_bearer_token_bedrock.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
