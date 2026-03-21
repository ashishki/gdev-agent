from __future__ import annotations

import pytest

import app.utils
from app.utils import run_blocking


async def _value() -> str:
    return "ok"


def test_run_blocking_runs_without_active_loop() -> None:
    assert run_blocking(_value()) == "ok"


@pytest.mark.asyncio
async def test_run_blocking_runs_with_active_loop() -> None:
    assert run_blocking(_value()) == "ok"


def test_run_blocking_re_raises_base_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ThreadStub:
        def __init__(self, *, target, daemon):  # noqa: ANN001
            _ = daemon
            self._target = target

        def start(self) -> None:
            self._target()

        def join(self) -> None:
            return None

    class _LoopStub:
        pass

    def _fake_asyncio_run(coroutine):  # noqa: ANN001
        coroutine.close()
        raise ValueError("boom")

    monkeypatch.setattr(app.utils.asyncio, "get_running_loop", lambda: _LoopStub())
    monkeypatch.setattr(app.utils.asyncio, "run", _fake_asyncio_run)
    monkeypatch.setattr(app.utils, "Thread", _ThreadStub)

    with pytest.raises(ValueError, match="boom"):
        run_blocking(_value())
