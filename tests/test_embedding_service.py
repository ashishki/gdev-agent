"""Embedding service tests for T13."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from uuid import uuid4

import pytest

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.embedding_service import EmbeddingService
from app.llm_client import TriageResult
from app.schemas import ClassificationResult, ExtractedFields, WebhookRequest
from app.store import EventStore


class _FakeLLMClient:
    def run_agent(
        self, text: str, user_id: str | None = None, max_turns: int = 5
    ) -> TriageResult:
        _ = (text, max_turns)
        return TriageResult(
            classification=ClassificationResult(
                category="other", urgency="low", confidence=0.99
            ),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="ok",
            input_tokens=10,
            output_tokens=5,
        )


class _SessionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self) -> "_SessionStub":
        return self

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.calls.append((str(statement), params or {}))
        return None


class _SessionFactoryStub:
    def __init__(self, session: _SessionStub) -> None:
        self._session = session

    def __call__(self) -> _SessionStub:
        return self._session


class _CapturingStore(EventStore):
    def __init__(self) -> None:
        super().__init__(sqlite_path=None)
        self.persisted_ticket_id = str(uuid4())

    def persist_pipeline_run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return self.persisted_ticket_id

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        _ = (event_type, payload)


class _SlowEmbeddingService:
    def __init__(self) -> None:
        self.calls = 0

    async def upsert(self, *, tenant_id: str, ticket_id: str, text_value: str) -> None:
        _ = (tenant_id, ticket_id, text_value)
        self.calls += 1
        await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_embedding_service_upsert_uses_voyage_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _SessionStub()
    service = EmbeddingService(
        settings=Settings(
            anthropic_api_key="k",
            voyage_api_key="voyage-key",
            embedding_model="voyage-3-lite",
        ),
        db_session_factory=_SessionFactoryStub(session),
    )

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"embedding": [0.1] * 1024}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(
        "app.embedding_service.httpx.AsyncClient", lambda **_: _Client()
    )
    await service.upsert(
        tenant_id=str(uuid4()),
        ticket_id=str(uuid4()),
        text_value="payment failed",
    )

    upsert_call = next(
        call for call in session.calls if "INSERT INTO ticket_embeddings" in call[0]
    )
    params = upsert_call[1]
    assert params["model_version"] == "voyage-3-lite"
    assert len(params["embedding"]) == 1024


@pytest.mark.asyncio
async def test_embedding_service_uses_deterministic_mock_vector_when_voyage_missing() -> (
    None
):
    session = _SessionStub()
    service = EmbeddingService(
        settings=Settings(anthropic_api_key="k", voyage_api_key=""),
        db_session_factory=_SessionFactoryStub(session),
    )
    tenant_id = str(uuid4())
    ticket_id = str(uuid4())

    await service.upsert(
        tenant_id=tenant_id, ticket_id=ticket_id, text_value="same text"
    )
    first_upsert = next(
        call for call in session.calls if "INSERT INTO ticket_embeddings" in call[0]
    )[1]

    session.calls.clear()
    await service.upsert(
        tenant_id=tenant_id, ticket_id=ticket_id, text_value="same text"
    )
    second_upsert = next(
        call for call in session.calls if "INSERT INTO ticket_embeddings" in call[0]
    )[1]

    assert len(first_upsert["embedding"]) == 1024
    assert first_upsert["embedding"] == second_upsert["embedding"]


@pytest.mark.asyncio
async def test_embedding_upsert_is_fire_and_forget_for_webhook_path() -> None:
    embedding_service = _SlowEmbeddingService()
    store = _CapturingStore()
    agent = AgentService(
        settings=Settings(
            anthropic_api_key="k",
            approval_categories=[],
            auto_approve_threshold=0.5,
            llm_input_rate_per_1k=Decimal("0.003"),
            llm_output_rate_per_1k=Decimal("0.015"),
        ),
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=_FakeLLMClient(),
        embedding_service=embedding_service,  # type: ignore[arg-type]
    )
    agent.execute_action = lambda *_args, **_kwargs: {
        "ticket": {"ticket_id": str(uuid4())}
    }  # type: ignore[method-assign]
    agent._append_audit_async = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    started = time.monotonic()
    response = agent.process_webhook(
        WebhookRequest(text="hello", user_id="u1", tenant_id=str(uuid4())),
        message_id="m1",
    )
    elapsed = time.monotonic() - started

    assert response.status == "executed"
    assert elapsed < 0.1
    await asyncio.sleep(0.25)
    assert embedding_service.calls == 1
