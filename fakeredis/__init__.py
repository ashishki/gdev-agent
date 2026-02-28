"""Lightweight local fakeredis fallback used in tests."""

from __future__ import annotations

import time


class FakeRedis:
    """Minimal Redis-like API for local tests."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}

    def _prune(self, key: str) -> None:
        exp = self._expires.get(key)
        if exp is not None and exp <= time.time():
            self._data.pop(key, None)
            self._expires.pop(key, None)

    def ping(self):
        return True

    def set(self, key: str, value, ex: int | None = None):
        self._data[key] = value if isinstance(value, str) else str(value)
        if ex is not None:
            self._expires[key] = time.time() + ex
        return True

    def get(self, key: str):
        self._prune(key)
        return self._data.get(key)

    def delete(self, key: str):
        self._data.pop(key, None)
        self._expires.pop(key, None)
        return 1

    def expire(self, key: str, seconds: int):
        if key in self._data:
            self._expires[key] = time.time() + seconds
            return 1
        return 0

    def ttl(self, key: str):
        self._prune(key)
        if key not in self._data:
            return -2
        exp = self._expires.get(key)
        if exp is None:
            return -1
        ttl = int(exp - time.time())
        return ttl if ttl > 0 else -2

    def incr(self, key: str):
        self._prune(key)
        current = int(self._data.get(key, "0"))
        current += 1
        self._data[key] = str(current)
        return current

    def execute_command(self, command: str, key: str):
        if command.upper() == "GETDEL":
            self._prune(key)
            value = self._data.pop(key, None)
            self._expires.pop(key, None)
            return value
        raise NotImplementedError(command)
