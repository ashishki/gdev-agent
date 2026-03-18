"""Dedup cache tests."""

from __future__ import annotations

import fakeredis

from app.dedup import DedupCache


def test_check_miss_returns_none() -> None:
    cache = DedupCache(fakeredis.FakeRedis())
    assert cache.check("tenant-a", "m1") is None


def test_set_then_check_returns_payload() -> None:
    redis_client = fakeredis.FakeRedis()
    cache = DedupCache(redis_client)
    cache.set("tenant-a", "m2", '{"status":"executed"}')
    assert cache.check("tenant-a", "m2") == '{"status":"executed"}'
    assert redis_client.get("tenant-a:dedup:m2") == '{"status":"executed"}'


def test_cross_tenant_message_id_isolation() -> None:
    redis_client = fakeredis.FakeRedis()
    cache = DedupCache(redis_client)
    cache.set("tenant-a", "shared-message", '{"status":"executed"}')

    assert cache.check("tenant-b", "shared-message") is None


def test_absent_message_id_skip_cache_flow() -> None:
    cache = DedupCache(fakeredis.FakeRedis())
    assert cache.check("tenant-a", "") is None
