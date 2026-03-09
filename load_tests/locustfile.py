"""Locust entrypoint with scenario selection and shared helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_messages.jsonl"


def load_sample_messages(path: Path = FIXTURES_PATH) -> list[dict[str, Any]]:
    """Load JSONL fixture messages for load testing."""
    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            messages.append(json.loads(raw))
    return messages


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Encode payload deterministically to match signature verification."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hmac_sign(payload_bytes: bytes, secret: str) -> str:
    """Create sha256 signature header value for webhook requests."""
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()


try:
    from locust import events

    from load_tests.scenarios.burst import BurstUser
    from load_tests.scenarios.steady import SteadyUser
    USER_CLASSES = (BurstUser, SteadyUser)

    @events.init_command_line_parser.add_listener
    def _add_scenario_arg(parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--scenario",
            type=str,
            default="burst",
            choices=["burst", "steady"],
            help="Load scenario to run",
        )

    @events.init.add_listener
    def _apply_scenario(environment, **_kwargs) -> None:  # noqa: ANN001
        selected = getattr(environment.parsed_options, "scenario", "burst")
        for user_class in environment.user_classes:
            user_scenario = getattr(user_class, "scenario_name", None)
            if user_scenario is None:
                continue
            user_class.weight = 1 if user_scenario == selected else 0

except ImportError:
    # Keep utility functions importable in unit tests when locust is not installed.
    pass
