"""Agent service tests for LLM draft and cost tracking."""

from __future__ import annotations

import fakeredis

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.llm_client import TriageResult
from app.schemas import ClassificationResult, ExtractedFields, WebhookRequest
from app.store import EventStore


class FakeLLMClient:
    def run_agent(self, text: str, user_id: str | None = None, max_turns: int = 5) -> TriageResult:
        _ = (text, max_turns)
        return TriageResult(
            classification=ClassificationResult(category="other", urgency="low", confidence=0.95),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="LLM draft response",
            input_tokens=100,
            output_tokens=50,
        )


class CapturingStore(EventStore):
    def __init__(self) -> None:
        super().__init__(sqlite_path=None)
        self.events: list[tuple[str, dict[str, object]]] = []

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


def test_webhook_uses_llm_draft_and_tracks_cost() -> None:
    settings = Settings(
        approval_categories=[],
        auto_approve_threshold=0.5,
        anthropic_input_cost_per_1k=0.003,
        anthropic_output_cost_per_1k=0.015,
    )
    store = CapturingStore()
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=FakeLLMClient(),
    )

    audit_entries = []
    agent._append_audit_async = lambda entry: audit_entries.append(entry)  # type: ignore[method-assign]

    response = agent.process_webhook(WebhookRequest(text="hello", user_id="u1"))

    assert response.draft_response == "LLM draft response"
    assert audit_entries[0].cost_usd > 0
    assert round(audit_entries[0].cost_usd, 6) == round(((100 / 1000) * 0.003) + ((50 / 1000) * 0.015), 6)

    event_payload = [payload for event, payload in store.events if event == "action_executed"][-1]
    assert event_payload["input_tokens"] == 100
    assert event_payload["output_tokens"] == 50
