"""Application configuration."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# WARNING: kb_base_url must appear in url_allowlist or FAQ URLs are silently stripped.
DEFAULT_KB_BASE_URL = "https://kb." + "example.com"


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "gdev-agent"
    app_env: str = "dev"
    log_level: str = "INFO"
    llm_mode: Literal["live", "demo"] = "live"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3-lite"
    kb_base_url: str = DEFAULT_KB_BASE_URL
    llm_input_rate_per_1k: Decimal = Field(
        default=Decimal("0.003"),
        validation_alias=AliasChoices("LLM_INPUT_RATE_PER_1K", "ANTHROPIC_INPUT_COST_PER_1K"),
    )
    llm_output_rate_per_1k: Decimal = Field(
        default=Decimal("0.015"),
        validation_alias=AliasChoices("LLM_OUTPUT_RATE_PER_1K", "ANTHROPIC_OUTPUT_COST_PER_1K"),
    )
    max_input_length: int = 2000
    auto_approve_threshold: float = 0.85
    exemplar_guard_enabled: bool = True
    exemplar_guard_threshold: float = 0.62
    exemplar_guard_top_k: int = 3
    exemplar_guard_examples_path: str | None = None
    approval_categories: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["billing"]
    )
    approval_ttl_seconds: int = 3600
    sqlite_log_path: str | None = None
    redis_url: str = "redis://redis:6379"
    database_url: PostgresDsn | None = None
    test_database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    output_guard_enabled: bool = True
    url_allowlist: Annotated[list[str], NoDecode] = Field(default_factory=list)
    output_url_behavior: Literal["strip", "reject"] = "strip"
    webhook_secret: str | None = None
    webhook_secret_encryption_key: str | None = None
    jwt_secret: str = "dev-jwt-secret-must-be-at-least-32b"
    jwt_algorithm: str = "HS256"
    jwt_token_expiry_hours: int = 8
    approve_secret: str | None = None
    rate_limit_rpm: int = 10
    rate_limit_burst: int = 3
    auth_rate_limit_attempts: int = 5
    rca_lookback_hours: int = 24
    rca_budget_per_run_usd: Decimal = Decimal("0.15")
    linear_api_key: str | None = None
    linear_team_id: str | None = None
    telegram_bot_token: str | None = None
    telegram_approval_chat_id: str | None = None
    google_sheets_credentials_json: str | None = None
    google_sheets_id: str | None = None
    otlp_endpoint: str = ""
    otel_service_name: str = "gdev-agent"

    @field_validator("approval_categories", mode="before")
    @classmethod
    def _parse_categories(cls, value: object) -> list[str]:
        """Allow comma-separated category values from env."""
        if value is None:
            return ["billing"]
        return _parse_string_list(value, default=["billing"])

    @field_validator("llm_mode", mode="before")
    @classmethod
    def _parse_llm_mode(cls, value: object) -> str:
        """Normalize LLM mode from env."""
        if value is None:
            return "live"
        return str(value).strip().lower()

    @field_validator("url_allowlist", mode="before")
    @classmethod
    def _parse_allowlist(cls, value: object) -> list[str]:
        """Allow comma-separated URL allowlist from env."""
        if value is None:
            return []
        return _parse_string_list(value, default=[])


def _parse_string_list(value: object, *, default: list[str]) -> list[str]:
    if isinstance(value, str):
        raw_value = value.strip()
        if not raw_value:
            return []
        if raw_value.startswith("["):
            try:
                decoded = json.loads(raw_value)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        parts = [part.strip().strip("\"'") for part in raw_value.split(",")]
        return [part for part in parts if part]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    settings = Settings()
    if settings.llm_mode == "live" and not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when LLM_MODE=live")
    return settings
