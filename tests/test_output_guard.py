"""Output guard unit tests."""

from __future__ import annotations

from app.config import Settings
from app.guardrails.output_guard import OutputGuard
from app.schemas import ProposedAction


def _action() -> ProposedAction:
    return ProposedAction(tool="create_ticket_and_reply", payload={})


def test_secret_pattern_blocks_anthropic_key() -> None:
    guard = OutputGuard(Settings(output_guard_enabled=True))
    result = guard.scan("token sk-ant-aBcD1234567890abcdeXXXX", 0.9, _action())
    assert result.blocked is True


def test_secret_pattern_blocks_linear_key() -> None:
    guard = OutputGuard(Settings(output_guard_enabled=True))
    result = guard.scan("lin_api_XyZ1234567890abcdeABCDE", 0.9, _action())
    assert result.blocked is True


def test_url_strip_behavior() -> None:
    guard = OutputGuard(
        Settings(output_guard_enabled=True, output_url_behavior="strip", url_allowlist=["kb.example.com"])
    )
    result = guard.scan("Read https://evil.example.com/link now", 0.9, _action())
    assert result.blocked is False
    assert "evil.example.com" not in result.redacted_draft


def test_url_allowlisted_passes() -> None:
    guard = OutputGuard(
        Settings(output_guard_enabled=True, output_url_behavior="strip", url_allowlist=["kb.example.com"])
    )
    draft = "See https://kb.example.com/tips"
    result = guard.scan(draft, 0.9, _action())
    assert result.redacted_draft == draft


def test_confidence_floor_forces_flag_for_human() -> None:
    action = _action()
    guard = OutputGuard(Settings(output_guard_enabled=True))
    result = guard.scan("ok", 0.3, action)
    assert result.blocked is False
    assert result.action_override is not None
    assert result.action_override.tool == "flag_for_human"
    assert result.action_override.risky is True
    assert result.action_override.risk_reason == "confidence below safety floor"
    assert action.tool == "create_ticket_and_reply"
    assert action.risky is False
    assert action.risk_reason is None


def test_guard_disabled_skips_checks() -> None:
    action = _action()
    guard = OutputGuard(Settings(output_guard_enabled=False))
    draft = "sk-ant-aBcD1234567890abcde and https://evil.example.com"
    result = guard.scan(draft, 0.3, action)
    assert result.blocked is False
    assert result.redacted_draft == draft
    assert action.tool == "create_ticket_and_reply"
