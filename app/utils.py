"""Shared utility helpers."""

from __future__ import annotations

import asyncio
from queue import Queue
from threading import Thread
from typing import Any, Coroutine, TypeVar, cast

T = TypeVar("T")


def run_blocking(coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def _target() -> None:
        try:
            result = asyncio.run(coroutine)
            queue.put((True, result))
        except Exception as exc:  # pragma: no cover - defensive branch
            queue.put((False, exc))

    thread = Thread(target=_target, daemon=True)
    thread.start()
    ok, data = queue.get()
    thread.join()
    if ok:
        return cast(T, data)
    raise data  # type: ignore[misc]
