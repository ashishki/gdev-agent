"""Output guard unit tests."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.exceptions import AgentError
from app.guardrails.output_guard import OutputGuard
from app.llm_client import TriageResult
from app.schemas import ClassificationResult, ExtractedFields, ProposedAction, WebhookRequest
from app.store import EventStore


def _action() -> ProposedAction:
    return ProposedAction(tool="create_ticket_and_reply", payload={})


class _UnsafeDraftLLM:
    def run_agent(
        self,
        text: str,
        user_id: str | None = None,
        max_turns: int = 5,
        tenant_id: str | None = None,
    ) -> TriageResult:
        _ = (text, max_turns, tenant_id)
        return TriageResult(
            classification=ClassificationResult(category="other", urgency="low", confidence=0.95),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="Read this unsafe link: https://evil.example.com/phish",
            input_tokens=10,
            output_tokens=10,
        )


def _sample(metric: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(metric, labels=labels)
    return float(value) if value is not None else 0.0


def test_secret_pattern_blocks_anthropic_key() -> None:
    guard = OutputGuard(Settings(output_guard_enabled=True))
    fake_key = "sk" + "-ant-aBcD1234567890abcdeXXXX"
    result = guard.scan(f"token {fake_key}", 0.9, _action())
    assert result.blocked is True


def test_secret_pattern_blocks_linear_key() -> None:
    guard = OutputGuard(Settings(output_guard_enabled=True))
    fake_key = "lin" + "_api_XyZ1234567890abcdeABCDE"
    result = guard.scan(fake_key, 0.9, _action())
    assert result.blocked is True


def test_url_strip_behavior() -> None:
    guard = OutputGuard(
        Settings(
            output_guard_enabled=True,
            output_url_behavior="strip",
            url_allowlist=["kb.example.com"],
        )
    )
    result = guard.scan("Read https://evil.example.com/link now", 0.9, _action())
    assert result.blocked is False
    assert "evil.example.com" not in result.redacted_draft


def test_url_allowlisted_passes() -> None:
    guard = OutputGuard(
        Settings(
            output_guard_enabled=True,
            output_url_behavior="strip",
            url_allowlist=["kb.example.com"],
        )
    )
    draft = "See https://kb.example.com/tips"
    result = guard.scan(draft, 0.9, _action())
    assert result.redacted_draft == draft


def test_output_guard_reject_url_records_block_metric() -> None:
    tenant_id = str(uuid4())
    tenant_hash = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    labels = {
        "guard_type": "output",
        "reason": "blocked_response",
        "tenant_hash": tenant_hash,
    }
    before = _sample("gdev_guard_blocks_total", labels)
    agent = AgentService(
        settings=Settings(
            output_guard_enabled=True,
            output_url_behavior="reject",
            url_allowlist=["kb.example.com"],
        ),
        store=EventStore(sqlite_path=None),
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=_UnsafeDraftLLM(),
    )

    with pytest.raises(AgentError) as exc:
        agent.process_webhook(
            WebhookRequest(text="send me a link", user_id="u1", tenant_id=tenant_id)
        )

    assert exc.value.detail == "Internal: output guard blocked response"
    assert _sample("gdev_guard_blocks_total", labels) == before + 1


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
    draft = "sk" + "-ant-aBcD1234567890abcde and https://evil.example.com"
    result = guard.scan(draft, 0.3, action)
    assert result.blocked is False
    assert result.redacted_draft == draft
    assert action.tool == "create_ticket_and_reply"
