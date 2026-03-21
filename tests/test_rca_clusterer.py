"""RCA clusterer tests for T14."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.jobs import rca_clusterer
from app.jobs.rca_clusterer import RCAClusterer

UTC = timezone.utc

class _ResultStub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "_ResultStub":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _SessionStub:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, object | None]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self) -> "_SessionStub":
        return self

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.calls.append((str(statement), params))
        return _ResultStub(self.rows)


class _SessionFactoryStub:
    def __init__(self, session: _SessionStub) -> None:
        self._session = session

    def __call__(self) -> _SessionStub:
        return self._session


class _LLMStub:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def summarize_cluster(self, texts: list[str]) -> dict[str, str | None]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("anthropic down")
        return {
            "label": "Payment issue",
            "summary": f"{len(texts)} tickets",
            "severity": "high",
        }

    async def summarize_cluster_async(self, texts: list[str]) -> dict[str, str | None]:
        return self.summarize_cluster(texts)


class _SpanStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []

    def __enter__(self) -> "_SpanStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _TracerStub:
    def __init__(self) -> None:
        self.spans: list[_SpanStub] = []

    def start_as_current_span(self, name: str) -> _SpanStub:
        span = _SpanStub(name)
        self.spans.append(span)
        return span


@pytest.mark.asyncio
async def test_run_tenant_caps_clusters_at_50(monkeypatch: pytest.MonkeyPatch) -> None:
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(_SessionStub()),
        llm_client=_LLMStub(),
        admin_session_factory=_SessionFactoryStub(_SessionStub()),
    )
    rows = [
        {
            "ticket_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "embedding": [0.1] * 4,
            "created_at": datetime.now(UTC) - timedelta(minutes=index),
        }
        for index in range(60)
    ]
    monkeypatch.setattr(
        clusterer, "_fetch_embeddings", lambda tenant_id: asyncio.sleep(0, rows)
    )
    monkeypatch.setattr(
        clusterer, "_deactivate_existing_clusters", lambda tenant_id: asyncio.sleep(0)
    )
    monkeypatch.setattr(
        clusterer,
        "_dbscan",
        lambda embeddings, eps, min_samples: list(range(len(embeddings))),
    )
    upserts: list[int] = []

    async def _capture_upsert(
        *, tenant_id: str, cluster_rows: list[dict[str, object]], cluster_number: int
    ) -> None:
        _ = (tenant_id, cluster_rows, cluster_number)
        upserts.append(cluster_number)

    monkeypatch.setattr(clusterer, "_upsert_cluster", _capture_upsert)

    await clusterer.run_tenant(str(uuid4()))
    assert len(upserts) == 50


@pytest.mark.asyncio
async def test_run_tenant_emits_run_and_cluster_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _TracerStub()
    tenant_id = str(uuid4())
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(_SessionStub()),
        llm_client=_LLMStub(),
        admin_session_factory=_SessionFactoryStub(_SessionStub()),
    )
    rows = [
        {
            "ticket_id": str(uuid4()),
            "tenant_id": tenant_id,
            "embedding": [0.1, 0.1, 0.1],
            "created_at": datetime.now(UTC),
        },
        {
            "ticket_id": str(uuid4()),
            "tenant_id": tenant_id,
            "embedding": [0.1, 0.1, 0.1],
            "created_at": datetime.now(UTC),
        },
    ]

    monkeypatch.setattr(rca_clusterer, "TRACER", tracer)
    monkeypatch.setattr(
        clusterer, "_fetch_embeddings", lambda tenant_id: asyncio.sleep(0, rows)
    )
    monkeypatch.setattr(
        clusterer, "_deactivate_existing_clusters", lambda tenant_id: asyncio.sleep(0)
    )
    monkeypatch.setattr(
        clusterer, "_dbscan", lambda embeddings, eps, min_samples: [0, 0]
    )
    monkeypatch.setattr(
        clusterer,
        "_upsert_cluster",
        lambda *, tenant_id, cluster_rows, cluster_number: asyncio.sleep(0),
    )

    await clusterer.run_tenant(tenant_id)

    spans = {span.name: span for span in tracer.spans}
    assert spans["rca.run"].attributes["tenant_id_hash"] == rca_clusterer._sha256_short(
        tenant_id
    )
    assert spans["rca.run"].attributes["ticket_count"] == 2
    assert spans["rca.cluster"].attributes["cluster_count"] == 1


@pytest.mark.asyncio
async def test_upsert_cluster_calls_llm_and_writes_summary() -> None:
    db_session = _SessionStub()
    llm = _LLMStub(fail=False)
    tenant_id = str(uuid4())
    admin_session = _SessionStub(
        rows=[{"tenant_id": tenant_id, "raw_text": "payment failed"}]
    )
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(db_session),
        llm_client=llm,
        admin_session_factory=_SessionFactoryStub(admin_session),
    )
    await clusterer._upsert_cluster(
        tenant_id=tenant_id,
        cluster_rows=[
            {"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)},
            {"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)},
        ],
        cluster_number=1,
    )

    assert llm.calls == 1
    upsert_params = db_session.calls[-1][1]
    assert upsert_params is not None
    assert upsert_params["label"] == "Payment issue"
    assert any(
        "INSERT INTO rca_cluster_members" in statement
        for statement, _ in admin_session.calls
    )


@pytest.mark.asyncio
async def test_upsert_cluster_emits_summarize_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _TracerStub()
    db_session = _SessionStub()
    llm = _LLMStub(fail=False)
    tenant_id = str(uuid4())
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(db_session),
        llm_client=llm,
        admin_session_factory=_SessionFactoryStub(
            _SessionStub(rows=[{"tenant_id": tenant_id, "raw_text": "payment failed"}])
        ),
    )
    monkeypatch.setattr(rca_clusterer, "TRACER", tracer)

    await clusterer._upsert_cluster(
        tenant_id=tenant_id,
        cluster_rows=[
            {"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)},
            {"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)},
        ],
        cluster_number=3,
    )

    summarize_spans = [span for span in tracer.spans if span.name == "rca.summarize"]
    assert len(summarize_spans) == 1
    assert summarize_spans[0].attributes["ticket_count"] == 2
    assert (
        summarize_spans[0].attributes["cluster_id"]
        == db_session.calls[-1][1]["cluster_id"]
    )


@pytest.mark.asyncio
async def test_upsert_cluster_uses_generic_label_on_llm_failure() -> None:
    db_session = _SessionStub()
    tenant_id = str(uuid4())
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(db_session),
        llm_client=_LLMStub(fail=True),
        admin_session_factory=_SessionFactoryStub(
            _SessionStub(
                rows=[{"tenant_id": tenant_id, "raw_text": "checkout timeout"}]
            )
        ),
    )
    await clusterer._upsert_cluster(
        tenant_id=tenant_id,
        cluster_rows=[{"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)}],
        cluster_number=7,
    )

    upsert_params = db_session.calls[-1][1]
    assert upsert_params is not None
    assert upsert_params["label"] == "Cluster 7"


@pytest.mark.asyncio
async def test_fetch_raw_texts_admin_raises_on_cross_tenant_row() -> None:
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(_SessionStub()),
        llm_client=_LLMStub(),
        admin_session_factory=_SessionFactoryStub(
            _SessionStub(
                rows=[
                    {
                        "tenant_id": "tenant-b",
                        "raw_text": "mismatched tenant row",
                    }
                ]
            )
        ),
    )

    with pytest.raises(ValueError, match="Cross-tenant"):
        await clusterer._fetch_raw_texts_admin(
            tenant_id="tenant-a", ticket_ids=[str(uuid4())]
        )


@pytest.mark.asyncio
async def test_run_with_timeout_wraps_runner_with_300_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(_SessionStub()),
        llm_client=_LLMStub(),
        admin_session_factory=_SessionFactoryStub(_SessionStub()),
    )
    seen = {"timeout": None, "called": False}

    async def _fake_wait_for(coro, timeout: float):
        seen["timeout"] = timeout
        await coro

    async def _fake_run_all() -> None:
        seen["called"] = True

    monkeypatch.setattr(clusterer, "run_for_all_tenants", _fake_run_all)
    monkeypatch.setattr("app.jobs.rca_clusterer.asyncio.wait_for", _fake_wait_for)

    await clusterer.run_with_timeout()
    assert seen["called"] is True
    assert seen["timeout"] == 300
