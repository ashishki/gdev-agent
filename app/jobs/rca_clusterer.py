"""RCA clustering background job."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.db import _set_tenant_ctx
from app.llm_client import LLMClient
from app.metrics import (
    RCA_CLUSTERS_ACTIVE,
    RCA_RUN_DURATION_SECONDS,
    RCA_TICKETS_SCANNED_TOTAL,
)
from app.tracing import get_tracer

LOGGER = logging.getLogger(__name__)
TRACER = get_tracer(__name__)

_RCA_CLUSTER_NAMESPACE = UUID("9f0fd1bc-5310-4ae3-a721-68d1327ec244")
UTC = timezone.utc


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _coerce_embedding(value: object) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, tuple):
        return [float(item) for item in value]
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [float(item) for item in parsed]
    raise ValueError("Unsupported embedding representation")


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    similarity = dot / (norm_a * norm_b)
    similarity = min(1.0, max(-1.0, similarity))
    return 1.0 - similarity


class RCAClusterer:
    """Cluster recent embeddings and write cluster summaries."""

    def __init__(
        self,
        settings: Settings,
        db_session_factory: async_sessionmaker[AsyncSession],
        llm_client: LLMClient | None = None,
        admin_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings
        self._db_session_factory = db_session_factory
        self._llm_client = llm_client or LLMClient(settings)
        self._admin_engine: AsyncEngine | None = None
        self._admin_session_factory = (
            admin_session_factory or self._build_admin_session_factory(settings)
        )

    def _build_admin_session_factory(
        self,
        settings: Settings,
    ) -> async_sessionmaker[AsyncSession] | None:
        database_url = (
            str(settings.database_url) if settings.database_url is not None else None
        )
        if not database_url:
            return None
        parsed: URL = make_url(database_url)
        if not parsed.username:
            return None
        admin_url = parsed.set(username="gdev_admin")
        self._admin_engine = create_async_engine(str(admin_url), pool_pre_ping=True)
        return async_sessionmaker(
            self._admin_engine, expire_on_commit=False, class_=AsyncSession
        )

    async def aclose(self) -> None:
        if self._admin_engine is not None:
            await self._admin_engine.dispose()

    async def run_with_timeout(self) -> None:
        """Run clusterer with a global timeout guard."""
        await asyncio.wait_for(self.run_for_all_tenants(), timeout=300)

    async def run_for_all_tenants(self) -> None:
        """Run RCA for all active tenants."""
        if self._admin_session_factory is None:
            return
        async with self._admin_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT tenant_id
                        FROM tenants
                        WHERE is_active = TRUE
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            await self.run_tenant(str(row["tenant_id"]))

    async def run_tenant(self, tenant_id: str) -> None:
        """Run RCA clustering for a single tenant."""
        tenant_hash = _sha256_short(tenant_id)
        started = time.monotonic()

        try:
            with TRACER.start_as_current_span("rca.run") as span:
                try:
                    span.set_attribute("tenant_id_hash", tenant_hash)
                    rows = await self._fetch_embeddings(tenant_id=tenant_id)
                    span.set_attribute("ticket_count", len(rows))
                    if not rows:
                        LOGGER.info(
                            "rca no tickets",
                            extra={
                                "event": "rca_no_tickets",
                                "context": {"tenant_id_hash": tenant_hash},
                            },
                        )
                        RCA_CLUSTERS_ACTIVE.labels(tenant_hash=tenant_hash).set(0)
                        return

                    embeddings = [_coerce_embedding(row["embedding"]) for row in rows]
                    with TRACER.start_as_current_span("rca.cluster") as cluster_span:
                        try:
                            labels = self._dbscan(embeddings, eps=0.15, min_samples=3)
                            clusters = self._collect_clusters(rows, labels)
                            cluster_span.set_attribute("cluster_count", len(clusters))
                        except Exception as exc:
                            cluster_span.record_exception(exc)
                            raise
                    budget_cap = max(
                        1,
                        min(
                            50,
                            int(
                                self._settings.rca_budget_per_run_usd / Decimal("0.003")
                            ),
                        ),
                    )
                    if len(clusters) > budget_cap:
                        LOGGER.warning(
                            "rca cluster cap hit",
                            extra={
                                "event": "rca_cluster_cap_hit",
                                "context": {
                                    "tenant_id_hash": tenant_hash,
                                    "clusters_before_cap": len(clusters),
                                    "clusters_after_cap": budget_cap,
                                },
                            },
                        )
                        clusters = clusters[:budget_cap]

                    await self._deactivate_existing_clusters(tenant_id=tenant_id)
                    for index, cluster_rows in enumerate(clusters, start=1):
                        await self._upsert_cluster(
                            tenant_id=tenant_id,
                            cluster_rows=cluster_rows,
                            cluster_number=index,
                        )

                    RCA_CLUSTERS_ACTIVE.labels(tenant_hash=tenant_hash).set(
                        len(clusters)
                    )
                    RCA_TICKETS_SCANNED_TOTAL.labels(tenant_hash=tenant_hash).inc(
                        len(rows)
                    )
                    LOGGER.info(
                        "rca run complete",
                        extra={
                            "event": "rca_run_complete",
                            "context": {
                                "tenant_id_hash": tenant_hash,
                                "ticket_count": len(rows),
                                "cluster_count": len(clusters),
                            },
                        },
                    )
                except Exception as exc:
                    span.record_exception(exc)
                    raise
        finally:
            RCA_RUN_DURATION_SECONDS.labels(tenant_hash=tenant_hash).observe(
                time.monotonic() - started
            )

    async def _fetch_embeddings(self, tenant_id: str) -> list[dict[str, object]]:
        lookback = datetime.now(UTC) - timedelta(
            hours=self._settings.rca_lookback_hours
        )
        async with self._db_session_factory() as session:
            try:
                async with session.begin():
                    await _set_tenant_ctx(session, tenant_id)
                    rows = (
                        (
                            await session.execute(
                                text(
                                    """
                                SELECT ticket_id, tenant_id, embedding, created_at
                                FROM ticket_embeddings
                                WHERE tenant_id = :tenant_id AND created_at > :lookback
                                ORDER BY embedding <-> (
                                    SELECT AVG(embedding)
                                    FROM ticket_embeddings
                                    WHERE tenant_id = :tenant_id
                                )
                                LIMIT 500
                                """
                                ),
                                {"tenant_id": tenant_id, "lookback": lookback},
                            )
                        )
                        .mappings()
                        .all()
                    )
            except Exception:
                LOGGER.warning("ANN fallback failed", exc_info=True)
                async with session.begin():
                    await _set_tenant_ctx(session, tenant_id)
                    rows = (
                        (
                            await session.execute(
                                text(
                                    """
                                SELECT ticket_id, tenant_id, embedding, created_at
                                FROM ticket_embeddings
                                WHERE tenant_id = :tenant_id AND created_at > :lookback
                                ORDER BY created_at DESC
                                LIMIT 500
                                """
                                ),
                                {"tenant_id": tenant_id, "lookback": lookback},
                            )
                        )
                        .mappings()
                        .all()
                    )
        return [dict(row) for row in rows]

    async def _deactivate_existing_clusters(self, tenant_id: str) -> None:
        async with self._db_session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, tenant_id)
                await session.execute(
                    text(
                        """
                        UPDATE cluster_summaries
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": tenant_id},
                )

    async def _upsert_cluster(
        self,
        *,
        tenant_id: str,
        cluster_rows: list[dict[str, object]],
        cluster_number: int,
    ) -> None:
        ticket_ids = [str(row["ticket_id"]) for row in cluster_rows]
        cluster_key = ",".join(sorted(ticket_ids))
        cluster_id = str(uuid5(_RCA_CLUSTER_NAMESPACE, f"{tenant_id}:{cluster_key}"))
        created_ats = [
            cast(datetime, row["created_at"])
            for row in cluster_rows
            if isinstance(row.get("created_at"), datetime)
        ]
        first_seen = min(created_ats) if created_ats else datetime.now(UTC)
        last_seen = max(created_ats) if created_ats else datetime.now(UTC)
        texts = await self._fetch_raw_texts_admin(
            tenant_id=tenant_id, ticket_ids=ticket_ids[:5]
        )
        label = f"Cluster {cluster_number}"
        summary = f"{len(cluster_rows)} related tickets"
        severity = self._severity_from_size(len(cluster_rows))
        try:
            if texts:
                with TRACER.start_as_current_span("rca.summarize") as span:
                    span.set_attribute("cluster_id", cluster_id)
                    span.set_attribute("ticket_count", len(cluster_rows))
                    try:
                        summary_result = await self._llm_client.summarize_cluster_async(
                            texts
                        )
                    except Exception as exc:
                        span.record_exception(exc)
                        raise
                label = summary_result.get("label") or label
                summary = summary_result.get("summary") or summary
                severity = summary_result.get("severity") or severity
        except Exception:
            LOGGER.warning(
                "rca summarize failed",
                extra={
                    "event": "rca_summarize_failed",
                    "context": {
                        "tenant_id_hash": _sha256_short(tenant_id),
                        "cluster_id": cluster_id,
                    },
                },
                exc_info=True,
            )
            label = f"Cluster {cluster_number}"

        async with self._db_session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, tenant_id)
                await session.execute(
                    text(
                        """
                        INSERT INTO cluster_summaries (
                            cluster_id, tenant_id, label, summary, ticket_count, severity,
                            first_seen, last_seen, is_active, updated_at
                        )
                        VALUES (
                            :cluster_id, :tenant_id, :label, :summary, :ticket_count, :severity,
                            :first_seen, :last_seen, TRUE, NOW()
                        )
                        ON CONFLICT (cluster_id) DO UPDATE
                        SET
                            label = EXCLUDED.label,
                            summary = EXCLUDED.summary,
                            ticket_count = EXCLUDED.ticket_count,
                            severity = EXCLUDED.severity,
                            first_seen = EXCLUDED.first_seen,
                            last_seen = EXCLUDED.last_seen,
                            is_active = TRUE,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "cluster_id": cluster_id,
                        "tenant_id": tenant_id,
                        "label": label,
                        "summary": summary,
                        "ticket_count": len(cluster_rows),
                        "severity": severity,
                        "first_seen": first_seen,
                        "last_seen": last_seen,
                    },
                )
        await self._replace_cluster_members_admin(
            cluster_id=cluster_id,
            ticket_ids=ticket_ids,
        )

    async def _replace_cluster_members_admin(
        self,
        *,
        cluster_id: str,
        ticket_ids: list[str],
    ) -> None:
        if self._admin_session_factory is None:
            return
        async with self._admin_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        DELETE FROM rca_cluster_members
                        WHERE cluster_id = :cluster_id
                        """
                    ),
                    {"cluster_id": cluster_id},
                )
                if not ticket_ids:
                    return
                await session.execute(
                    text(
                        """
                        INSERT INTO rca_cluster_members (cluster_id, ticket_id)
                        VALUES (:cluster_id, :ticket_id)
                        """
                    ),
                    [
                        {"cluster_id": cluster_id, "ticket_id": ticket_id}
                        for ticket_id in ticket_ids
                    ],
                )

    async def _fetch_raw_texts_admin(
        self, *, tenant_id: str, ticket_ids: list[str]
    ) -> list[str]:
        if not ticket_ids or self._admin_session_factory is None:
            return []
        statement = text(
            """
                SELECT tenant_id, raw_text
                FROM tickets
                WHERE tenant_id = :tenant_id AND ticket_id IN :ticket_ids
                ORDER BY created_at DESC
                LIMIT 5
                """
        ).bindparams(bindparam("ticket_ids", expanding=True))
        async with self._admin_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        statement,
                        {
                            "tenant_id": tenant_id,
                            "ticket_ids": [UUID(ticket_id) for ticket_id in ticket_ids],
                        },
                    )
                )
                .mappings()
                .all()
            )

        texts: list[str] = []
        for row in rows:
            cluster_tenant_id = str(row["tenant_id"])
            if cluster_tenant_id != tenant_id:
                LOGGER.error(
                    "cross-tenant row detected in admin fetch",
                    extra={
                        "event": "rca_cross_tenant_breach",
                        "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                    },
                )
                raise ValueError(
                    "Cross-tenant isolation breach: "
                    f"got {_sha256_short(cluster_tenant_id)}, "
                    f"expected {_sha256_short(tenant_id)}"
                )
            text_value = row.get("raw_text")
            if isinstance(text_value, str):
                texts.append(text_value)
        return texts

    def _collect_clusters(
        self,
        rows: list[dict[str, object]],
        labels: list[int],
    ) -> list[list[dict[str, object]]]:
        grouped: dict[int, list[dict[str, object]]] = {}
        for row, label in zip(rows, labels, strict=True):
            if label == -1:
                continue
            grouped.setdefault(label, []).append(row)
        clusters = list(grouped.values())
        clusters.sort(key=len, reverse=True)
        return clusters

    def _dbscan(
        self, embeddings: list[list[float]], *, eps: float, min_samples: int
    ) -> list[int]:
        n = len(embeddings)
        labels = [-1] * n
        visited = [False] * n
        cluster_id = 0

        neighbors_cache: dict[int, list[int]] = {}

        def neighbors(index: int) -> list[int]:
            if index in neighbors_cache:
                return neighbors_cache[index]
            points = [
                candidate
                for candidate in range(n)
                if _cosine_distance(embeddings[index], embeddings[candidate]) <= eps
            ]
            neighbors_cache[index] = points
            return points

        for index in range(n):
            if visited[index]:
                continue
            visited[index] = True
            seed_neighbors = neighbors(index)
            if len(seed_neighbors) < min_samples:
                labels[index] = -1
                continue

            labels[index] = cluster_id
            queue = list(seed_neighbors)
            while queue:
                candidate = queue.pop()
                if not visited[candidate]:
                    visited[candidate] = True
                    candidate_neighbors = neighbors(candidate)
                    if len(candidate_neighbors) >= min_samples:
                        for point in candidate_neighbors:
                            if point not in queue:
                                queue.append(point)
                if labels[candidate] == -1:
                    labels[candidate] = cluster_id
            cluster_id += 1
        return labels

    def _severity_from_size(self, size: int) -> str:
        if size >= 20:
            return "high"
        if size >= 8:
            return "medium"
        return "low"
