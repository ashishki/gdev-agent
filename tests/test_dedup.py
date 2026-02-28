"""Dedup cache tests."""

from __future__ import annotations

import fakeredis

from app.dedup import DedupCache


def test_check_miss_returns_none() -> None:
    cache = DedupCache(fakeredis.FakeRedis())
    assert cache.check("m1") is None


def test_set_then_check_returns_payload() -> None:
    cache = DedupCache(fakeredis.FakeRedis())
    cache.set("m2", '{"status":"executed"}')
    assert cache.check("m2") == '{"status":"executed"}'


def test_absent_message_id_skip_cache_flow() -> None:
    cache = DedupCache(fakeredis.FakeRedis())
    assert cache.check("") is None
