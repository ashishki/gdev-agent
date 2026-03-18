from __future__ import annotations

import pytest

from app.utils import run_blocking


async def _value() -> str:
    return "ok"


def test_run_blocking_runs_without_active_loop() -> None:
    assert run_blocking(_value()) == "ok"


@pytest.mark.asyncio
async def test_run_blocking_runs_with_active_loop() -> None:
    assert run_blocking(_value()) == "ok"
