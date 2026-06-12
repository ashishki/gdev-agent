"""Locust entrypoint with scenario selection and shared helpers."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_messages.jsonl"
SECRET_FRAGMENTS = ("sk-" + "ant", "lin_" + "api_", "AK" + "IA", "Bearer" + " ")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d .()/-]{8,}\d)")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


@dataclass(frozen=True)
class TenantProfile:
    """Synthetic tenant used by the local load harness."""

    slug: str
    tenant_id: str
    webhook_secret: str


@dataclass(frozen=True)
class ScenarioConfig:
    """Deterministic load profile knobs shared by Locust user classes."""

    name: str
    tenant_count: int
    case_types: tuple[str, ...]
    duplicate_replay: bool = False
    provider_latency_ms: int = 0
    burst_user_weight: int = 1
    steady_user_weight: int = 1
    estimated_cost_per_request_usd: float = 0.0008


TENANT_PROFILES: tuple[TenantProfile, ...] = (
    TenantProfile("test-tenant-a", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "test-webhook-secret-a"),
    TenantProfile("test-tenant-b", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "test-webhook-secret-b"),
    TenantProfile(
        "load-tenant-03", "00000000-0000-4000-8000-000000000003", "load-webhook-secret-03"
    ),
    TenantProfile(
        "load-tenant-04", "00000000-0000-4000-8000-000000000004", "load-webhook-secret-04"
    ),
    TenantProfile(
        "load-tenant-05", "00000000-0000-4000-8000-000000000005", "load-webhook-secret-05"
    ),
    TenantProfile(
        "load-tenant-06", "00000000-0000-4000-8000-000000000006", "load-webhook-secret-06"
    ),
    TenantProfile(
        "load-tenant-07", "00000000-0000-4000-8000-000000000007", "load-webhook-secret-07"
    ),
    TenantProfile(
        "load-tenant-08", "00000000-0000-4000-8000-000000000008", "load-webhook-secret-08"
    ),
    TenantProfile(
        "load-tenant-09", "00000000-0000-4000-8000-000000000009", "load-webhook-secret-09"
    ),
    TenantProfile(
        "load-tenant-10", "00000000-0000-4000-8000-000000000010", "load-webhook-secret-10"
    ),
)

SCENARIO_CONFIGS: dict[str, ScenarioConfig] = {
    "low_load": ScenarioConfig(
        name="low_load",
        tenant_count=1,
        case_types=("normal", "low_confidence"),
        burst_user_weight=0,
        steady_user_weight=1,
    ),
    "mixed_10_tenant": ScenarioConfig(
        name="mixed_10_tenant",
        tenant_count=10,
        case_types=("normal", "risky", "adversarial", "low_confidence"),
        burst_user_weight=2,
        steady_user_weight=3,
    ),
    "duplicate_replay": ScenarioConfig(
        name="duplicate_replay",
        tenant_count=1,
        case_types=("duplicate",),
        duplicate_replay=True,
        burst_user_weight=1,
        steady_user_weight=0,
        estimated_cost_per_request_usd=0.0,
    ),
    "risky_action_heavy": ScenarioConfig(
        name="risky_action_heavy",
        tenant_count=2,
        case_types=("risky", "low_confidence"),
        burst_user_weight=2,
        steady_user_weight=1,
    ),
    "provider_latency": ScenarioConfig(
        name="provider_latency",
        tenant_count=2,
        case_types=("normal", "risky", "low_confidence"),
        provider_latency_ms=750,
        burst_user_weight=1,
        steady_user_weight=2,
    ),
}

SCENARIO_ALIASES = {
    "steady": "low_load",
    "burst": "mixed_10_tenant",
}


def _iter_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            if key in {"tenant_id", "message_id"}:
                continue
            values.extend(_iter_string_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_iter_string_values(item))
        return values
    return []


def validate_sample_messages(messages: list[dict[str, Any]]) -> list[str]:
    """Return fixture safety errors for real PII or secret-like content."""
    errors: list[str] = []
    for line_number, message in enumerate(messages, start=1):
        message_id = str(message.get("message_id") or f"line-{line_number}")
        for field in ("tenant_id", "message_id", "user_id", "text"):
            if not str(message.get(field, "")).strip():
                errors.append(f"{message_id}: missing {field}")

        metadata = message.get("metadata", {})
        if not isinstance(metadata, dict):
            errors.append(f"{message_id}: metadata must be an object")

        for value in _iter_string_values(message):
            if any(fragment in value for fragment in SECRET_FRAGMENTS):
                errors.append(f"{message_id}: secret-like fixture value")
            if EMAIL_PATTERN.search(value):
                errors.append(f"{message_id}: email-like PII")
            if PHONE_PATTERN.search(value):
                errors.append(f"{message_id}: phone-like PII")
            if CREDIT_CARD_PATTERN.search(value):
                errors.append(f"{message_id}: payment-card-like PII")
    return errors


def load_sample_messages(path: Path = FIXTURES_PATH) -> list[dict[str, Any]]:
    """Load JSONL fixture messages for load testing."""
    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            messages.append(json.loads(raw))
    errors = validate_sample_messages(messages)
    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Unsafe load-test fixture values:\n{formatted}")
    return messages


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Encode payload deterministically to match signature verification."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hmac_sign(payload_bytes: bytes, secret: str) -> str:
    """Create sha256 signature header value for webhook requests."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def resolve_scenario(name: str | None) -> ScenarioConfig:
    """Resolve a public scenario name, including legacy aliases."""
    selected = name or os.getenv("LOAD_TEST_SCENARIO", "low_load")
    selected = SCENARIO_ALIASES.get(selected, selected)
    try:
        return SCENARIO_CONFIGS[selected]
    except KeyError as exc:
        valid = ", ".join(sorted((*SCENARIO_CONFIGS, *SCENARIO_ALIASES)))
        raise ValueError(f"Unknown load scenario {selected!r}. Valid scenarios: {valid}") from exc


def scenario_from_environment(environment: Any) -> ScenarioConfig:
    parsed_options = getattr(environment, "parsed_options", None)
    return resolve_scenario(getattr(parsed_options, "scenario", None))


def selected_tenants(config: ScenarioConfig) -> tuple[TenantProfile, ...]:
    """Select deterministic tenants, with a single-tenant env override for demos."""
    slug_override = os.getenv("LOAD_TEST_TENANT_SLUG")
    tenant_id_override = os.getenv("LOAD_TEST_TENANT_ID")
    secret_override = os.getenv("LOAD_TEST_WEBHOOK_SECRET")
    if slug_override and tenant_id_override and secret_override:
        return (TenantProfile(slug_override, tenant_id_override, secret_override),)

    requested = int(os.getenv("LOAD_TEST_TENANT_COUNT", str(config.tenant_count)))
    requested = max(1, min(requested, len(TENANT_PROFILES)))
    return TENANT_PROFILES[:requested]


def messages_for_scenario(
    messages: list[dict[str, Any]], config: ScenarioConfig
) -> list[dict[str, Any]]:
    """Filter fixture rows by scenario case type."""
    filtered = [
        message
        for message in messages
        if str(message.get("metadata", {}).get("case_type", "normal")) in config.case_types
    ]
    return filtered or messages


def build_webhook_request(
    messages: list[dict[str, Any]],
    config: ScenarioConfig,
    *,
    request_prefix: str,
) -> tuple[bytes, dict[str, str], dict[str, Any]]:
    """Build a signed webhook request for the selected scenario."""
    tenant = random.choice(selected_tenants(config))
    candidates = messages_for_scenario(messages, config)
    payload = copy.deepcopy(random.choice(candidates))
    payload["tenant_id"] = tenant.tenant_id
    payload.setdefault("metadata", {})
    payload["metadata"]["load_scenario"] = config.name
    payload["metadata"]["tenant_slug"] = tenant.slug

    if config.duplicate_replay:
        payload["message_id"] = "load-duplicate-replay-01"
    else:
        payload["message_id"] = f"{request_prefix}-{uuid.uuid4().hex}"

    body = serialize_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-Slug": tenant.slug,
        "X-Webhook-Signature": hmac_sign(body, tenant.webhook_secret),
        "X-Request-ID": uuid.uuid4().hex,
    }
    return body, headers, payload


def record_kpi(environment: Any, name: str, count: int = 1) -> None:
    """Emit a zero-latency Locust request event for KPI counting."""
    events_obj = getattr(environment, "events", None)
    request_event = getattr(events_obj, "request", None)
    fire = getattr(request_event, "fire", None)
    if fire is None:
        return
    for _ in range(count):
        fire(
            request_type="KPI",
            name=name,
            response_time=0,
            response_length=0,
            exception=None,
            context={},
        )


def simulate_provider_latency(environment: Any, config: ScenarioConfig) -> None:
    """Simulate provider latency in deterministic mode without calling a live LLM."""
    if config.provider_latency_ms <= 0:
        return
    try:
        from gevent import sleep as cooperative_sleep
    except ImportError:  # pragma: no cover - locust installs gevent in real runs
        cooperative_sleep = time.sleep
    cooperative_sleep(config.provider_latency_ms / 1000)
    record_kpi(environment, "provider_latency_simulated")


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
            default="low_load",
            choices=sorted((*SCENARIO_CONFIGS, *SCENARIO_ALIASES)),
            help="Load scenario to run",
        )

    @events.init.add_listener
    def _apply_scenario(environment, **_kwargs) -> None:  # noqa: ANN001
        config = scenario_from_environment(environment)
        for user_class in environment.user_classes:
            if getattr(user_class, "scenario_name", None) == "burst":
                user_class.weight = config.burst_user_weight
            if getattr(user_class, "scenario_name", None) == "steady":
                user_class.weight = config.steady_user_weight

except ImportError:
    # Keep utility functions importable in unit tests when locust is not installed.
    pass
