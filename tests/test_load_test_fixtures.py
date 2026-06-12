"""Load test fixture and HMAC utility tests."""

from __future__ import annotations

from pathlib import Path

from load_tests.check_kpis import build_report, format_report
from load_tests.locustfile import (
    SCENARIO_CONFIGS,
    TENANT_PROFILES,
    build_webhook_request,
    hmac_sign,
    load_sample_messages,
    serialize_payload,
    validate_sample_messages,
)
from scripts.seed_db import DEMO_SUPPORT_CASES


def test_sample_messages_jsonl_parses() -> None:
    fixture_path = Path("load_tests/fixtures/sample_messages.jsonl")
    messages = load_sample_messages(fixture_path)

    assert len(messages) == 50
    assert all("text" in message for message in messages)
    assert all("tenant_id" in message for message in messages)


def test_load_profiles_cover_t15_scenarios() -> None:
    messages = load_sample_messages(Path("load_tests/fixtures/sample_messages.jsonl"))
    required_profiles = {
        "low_load",
        "mixed_10_tenant",
        "duplicate_replay",
        "risky_action_heavy",
        "provider_latency",
    }
    observed_profiles = {
        profile
        for message in messages
        for profile in message.get("metadata", {}).get("load_profiles", [])
    }

    assert required_profiles <= set(SCENARIO_CONFIGS)
    assert required_profiles <= observed_profiles
    assert SCENARIO_CONFIGS["low_load"].tenant_count == 1
    assert SCENARIO_CONFIGS["mixed_10_tenant"].tenant_count == 10
    assert SCENARIO_CONFIGS["duplicate_replay"].duplicate_replay is True
    assert SCENARIO_CONFIGS["provider_latency"].provider_latency_ms > 0
    assert len(TENANT_PROFILES) == 10


def test_demo_support_case_contract_matches_fixture_and_docs() -> None:
    fixture_path = Path("load_tests/fixtures/sample_messages.jsonl")
    docs = Path("docs/DEMO.md").read_text(encoding="utf-8")
    messages = load_sample_messages(fixture_path)
    required_case_types = {
        "normal",
        "risky",
        "adversarial",
        "low_confidence",
        "duplicate",
    }

    observed_case_types = {
        str(message.get("metadata", {}).get("case_type"))
        for message in messages
        if message.get("metadata", {}).get("case_type")
    }
    assert required_case_types <= observed_case_types

    for case in DEMO_SUPPORT_CASES:
        case_type = case["case_type"]
        message_id = case["message_id"]
        case_fixture_path = Path(case["fixture_file"])
        matches = [
            message
            for message in messages
            if message.get("message_id") == message_id
            and message.get("metadata", {}).get("case_type") == case_type
        ]

        assert case_fixture_path == fixture_path
        assert case_fixture_path.exists()
        assert matches, f"missing demo support case fixture: {case}"
        assert case_type in docs
        assert message_id in docs

    duplicate_rows = [
        message for message in messages if message.get("message_id") == "sample-duplicate-01"
    ]
    assert len(duplicate_rows) == 2


def test_demo_fixture_text_contains_no_real_secret_patterns() -> None:
    messages = load_sample_messages(Path("load_tests/fixtures/sample_messages.jsonl"))
    forbidden_fragments = ("sk-" + "ant", "lin_" + "api_", "AK" + "IA", "Bearer" + " ")

    for message in messages:
        text = str(message.get("text", ""))
        assert not any(fragment in text for fragment in forbidden_fragments)


def test_fixture_validation_rejects_real_pii_and_secrets() -> None:
    unsafe_messages = [
        {
            "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "message_id": "unsafe-1",
            "user_id": "user-unsafe",
            "text": "Contact player@example.com with token " + ("sk-" + "ant") + "-demo",
            "metadata": {"chat_id": "chat-unsafe"},
        }
    ]

    errors = validate_sample_messages(unsafe_messages)

    assert any("email-like PII" in error for error in errors)
    assert any("secret-like fixture value" in error for error in errors)


def test_hmac_sign_matches_known_sha256() -> None:
    payload = {
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "message_id": "m-1",
        "user_id": "u-1",
        "text": "charged twice",
    }
    signature = hmac_sign(serialize_payload(payload), "secret")
    assert signature == "sha256=9f4c674caf64b290ead19e2c5e540a99805ab409f1990b45b42904caf01de631"


def test_duplicate_replay_payload_preserves_message_id_and_signature() -> None:
    messages = load_sample_messages(Path("load_tests/fixtures/sample_messages.jsonl"))
    config = SCENARIO_CONFIGS["duplicate_replay"]

    body, headers, payload = build_webhook_request(
        messages,
        config,
        request_prefix="test",
    )

    assert payload["message_id"] == "load-duplicate-replay-01"
    assert payload["metadata"]["load_scenario"] == "duplicate_replay"
    assert headers["X-Tenant-Slug"] == "test-tenant-a"
    assert headers["X-Webhook-Signature"] == hmac_sign(body, "test-webhook-secret-a")


def test_kpi_checker_reports_required_metrics(tmp_path: Path) -> None:
    stats_path = tmp_path / "stats.csv"
    stats_path.write_text(
        "\n".join(
            (
                "Type,Name,Request Count,Failure Count,50%,95%,99%",
                "POST,POST /webhook,100,1,110,450,900",
                "KPI,pending_approval,20,0,0,0,0",
                "KPI,dedup_hit_expected,12,0,0,0,0",
                "KPI,guard_block,4,0,0,0,0",
                "Aggregated,Aggregated,100,1,120,500,950",
            )
        ),
        encoding="utf-8",
    )

    report = build_report(stats_path, estimated_cost_per_request_usd=0.0012)
    formatted = format_report(report)

    assert report.request_count == 100
    assert report.p50_ms == 110
    assert report.p95_ms == 450
    assert report.p99_ms == 900
    assert report.error_rate == 0.01
    assert report.pending_approval_rate == 0.2
    assert report.dedup_hit_rate == 0.12
    assert report.guard_block_rate == 0.04
    assert report.estimated_cost_per_request_usd == 0.0012
    assert "p50_latency_ms=" in formatted
    assert "p95_latency_ms=" in formatted
    assert "p99_latency_ms=" in formatted
    assert "pending_approval_rate=" in formatted
    assert "dedup_hit_rate=" in formatted
    assert "guard_block_rate=" in formatted
    assert "estimated_cost_per_request_usd=" in formatted
