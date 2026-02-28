"""Application configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "gdev-agent"
    app_env: str = "dev"
    log_level: str = "INFO"
    max_input_length: int = 2000
    auto_approve_threshold: float = 0.85
    approval_categories: list[str] = Field(default_factory=lambda: ["billing"])
    sqlite_log_path: str | None = None

    @field_validator("approval_categories", mode="before")
    @classmethod
    def _parse_categories(cls, value: object) -> list[str]:
        """Allow comma-separated category values from env."""
        if value is None:
            return ["billing"]
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [part for part in parts if part]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return ["billing"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
