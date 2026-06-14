from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_settings_parse_comma_and_json_list_env_values(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("APPROVAL_CATEGORIES", "billing,account_access")
    monkeypatch.setenv("URL_ALLOWLIST", '["kb.example.com", "support.example.com"]')

    settings = Settings(llm_mode="demo")

    assert settings.approval_categories == ["billing", "account_access"]
    assert settings.url_allowlist == ["kb.example.com", "support.example.com"]


def test_settings_accept_cost_rate_env_aliases(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LLM_INPUT_RATE_PER_1K", "0.004")
    monkeypatch.setenv("LLM_OUTPUT_RATE_PER_1K", "0.020")

    settings = Settings(llm_mode="demo")

    assert settings.llm_input_rate_per_1k == Decimal("0.004")
    assert settings.llm_output_rate_per_1k == Decimal("0.020")


def test_settings_accept_legacy_cost_env_aliases(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("LLM_INPUT_RATE_PER_1K", raising=False)
    monkeypatch.delenv("LLM_OUTPUT_RATE_PER_1K", raising=False)
    monkeypatch.setenv("ANTHROPIC_INPUT_COST_PER_1K", "0.005")
    monkeypatch.setenv("ANTHROPIC_OUTPUT_COST_PER_1K", "0.025")

    settings = Settings(llm_mode="demo")

    assert settings.llm_input_rate_per_1k == Decimal("0.005")
    assert settings.llm_output_rate_per_1k == Decimal("0.025")


def test_env_example_parses_under_runtime_settings() -> None:
    settings = Settings(_env_file=ROOT / ".env.example")

    assert settings.llm_mode == "demo"
    assert settings.approval_categories == ["billing", "account_access"]
    assert settings.url_allowlist == ["kb.yourdomain.com"]
    assert settings.llm_input_rate_per_1k == Decimal("0.003")
    assert settings.llm_output_rate_per_1k == Decimal("0.015")


def test_compose_uses_portable_healthcheck_and_live_key_interpolation() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "LLM_MODE: ${LLM_MODE:-demo}" in compose
    assert "ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}" in compose
    assert "urllib.request.urlopen" in compose
    assert "curl -fsS" not in compose


def test_dockerignore_excludes_local_secret_files() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore
    assert "!.env.example" in dockerignore
    assert ".git" in dockerignore
