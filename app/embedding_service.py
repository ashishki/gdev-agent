"""Embedding generation and persistence for ticket text."""

from __future__ import annotations

import hashlib
import logging
import time
from uuid import UUID

import httpx
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing import Literal

from app.config import Settings

LOGGER = logging.getLogger(__name__)
try:  # pragma: no cover - optional dependency in local test env
    from opentelemetry import trace  # type: ignore[import-not-found]

    TRACER = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - fallback when opentelemetry is unavailable

    class _NoopSpan:
        def __enter__(self) -> "_NoopSpan":
            return self

        def __exit__(self, exc_type, exc, tb) -> Literal[False]:
            return False

        def set_attribute(self, _name: str, _value: object) -> None:
            return None

        def record_exception(self, _exc: BaseException) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, _name: str) -> _NoopSpan:
            return _NoopSpan()

    TRACER = _NoopTracer()

EMBEDDING_UPSERTS_TOTAL = Counter(
    "gdev_embedding_upserts_total",
    "Embedding upsert attempts by status",
    ["tenant_hash", "status"],
)
EMBEDDING_DURATION_SECONDS = Histogram(
    "gdev_embedding_duration_seconds",
    "Embedding upsert latency in seconds",
    ["tenant_hash"],
)


class _VoyageEmbeddingData(BaseModel):
    embedding: list[float]


class _VoyageEmbeddingResponse(BaseModel):
    data: list[_VoyageEmbeddingData]


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class EmbeddingService:
    """Generate ticket embeddings and persist them to Postgres."""

    def __init__(
        self,
        settings: Settings,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._db_session_factory = db_session_factory

    async def upsert(self, *, tenant_id: str, ticket_id: str, text_value: str) -> None:
        """Generate a 1024-dim embedding and upsert it for the ticket."""
        tenant_hash = _sha256_short(tenant_id)
        started = time.monotonic()

        with TRACER.start_as_current_span("service.embedding_service.upsert") as span:
            span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("model_version", self._settings.embedding_model)
            try:
                embedding = await self._embed_text(text_value)
                if len(embedding) != 1024:
                    raise ValueError(
                        f"Expected embedding size 1024, got {len(embedding)}"
                    )

                async with self._db_session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            text("SET LOCAL app.current_tenant_id = :tenant_id"),
                            {"tenant_id": tenant_id},
                        )
                        await session.execute(
                            text(
                                """
                                INSERT INTO ticket_embeddings (ticket_id, tenant_id, embedding, model_version)
                                VALUES (:ticket_id, :tenant_id, :embedding, :model_version)
                                ON CONFLICT (ticket_id) DO UPDATE
                                SET embedding=:embedding, model_version=:model_version, created_at=NOW()
                                """
                            ),
                            {
                                "ticket_id": str(UUID(ticket_id)),
                                "tenant_id": str(UUID(tenant_id)),
                                "embedding": embedding,
                                "model_version": self._settings.embedding_model,
                            },
                        )

                EMBEDDING_UPSERTS_TOTAL.labels(
                    tenant_hash=tenant_hash, status="ok"
                ).inc()
            except Exception as exc:
                EMBEDDING_UPSERTS_TOTAL.labels(
                    tenant_hash=tenant_hash, status="error"
                ).inc()
                span.record_exception(exc)
                LOGGER.warning(
                    "embedding upsert failed",
                    extra={
                        "event": "embedding_upsert_failed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                    exc_info=True,
                )
                raise
            finally:
                duration = time.monotonic() - started
                EMBEDDING_DURATION_SECONDS.labels(tenant_hash=tenant_hash).observe(
                    duration
                )

    async def _embed_text(self, text_value: str) -> list[float]:
        if not self._settings.voyage_api_key:
            return self._mock_embedding(text_value)

        payload = {"input": text_value, "model": self._settings.embedding_model}
        headers = {"Authorization": f"Bearer {self._settings.voyage_api_key}"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings", json=payload, headers=headers
            )
        response.raise_for_status()
        try:
            parsed = _VoyageEmbeddingResponse.model_validate(response.json())
        except ValidationError as exc:
            raise ValueError("Voyage API response failed validation") from exc

        if not parsed.data:
            raise ValueError("Voyage API returned no embedding data")
        return parsed.data[0].embedding

    def _mock_embedding(self, text_value: str) -> list[float]:
        digest = hashlib.sha256(text_value.encode("utf-8")).digest()
        values: list[float] = []
        for index in range(1024):
            byte = digest[index % len(digest)]
            values.append((byte / 255.0) * 2.0 - 1.0)
        return values
