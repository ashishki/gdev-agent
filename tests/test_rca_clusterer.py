"""RCA clusterer tests for T14."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.config import Settings
from app.jobs.rca_clusterer import RCAClusterer


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
        self.calls: list[tuple[str, dict[str, object] | None]] = []

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
async def test_upsert_cluster_calls_llm_and_writes_summary() -> None:
    db_session = _SessionStub()
    llm = _LLMStub(fail=False)
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(db_session),
        llm_client=llm,
        admin_session_factory=_SessionFactoryStub(
            _SessionStub(rows=[{"tenant_id": "tenant-1", "raw_text": "payment failed"}])
        ),
    )
    await clusterer._upsert_cluster(
        tenant_id="tenant-1",
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


@pytest.mark.asyncio
async def test_upsert_cluster_uses_generic_label_on_llm_failure() -> None:
    db_session = _SessionStub()
    clusterer = RCAClusterer(
        settings=Settings(anthropic_api_key="k"),
        db_session_factory=_SessionFactoryStub(db_session),
        llm_client=_LLMStub(fail=True),
        admin_session_factory=_SessionFactoryStub(
            _SessionStub(
                rows=[{"tenant_id": "tenant-2", "raw_text": "checkout timeout"}]
            )
        ),
    )
    await clusterer._upsert_cluster(
        tenant_id="tenant-2",
        cluster_rows=[{"ticket_id": str(uuid4()), "created_at": datetime.now(UTC)}],
        cluster_number=7,
    )

    upsert_params = db_session.calls[-1][1]
    assert upsert_params is not None
    assert upsert_params["label"] == "Cluster 7"


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
