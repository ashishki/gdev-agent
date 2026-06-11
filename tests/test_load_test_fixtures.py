"""Load test fixture and HMAC utility tests."""

from __future__ import annotations

from pathlib import Path

from load_tests.locustfile import hmac_sign, load_sample_messages, serialize_payload
from scripts.seed_db import DEMO_SUPPORT_CASES


def test_sample_messages_jsonl_parses() -> None:
    fixture_path = Path("load_tests/fixtures/sample_messages.jsonl")
    messages = load_sample_messages(fixture_path)

    assert len(messages) == 50
    assert all("text" in message for message in messages)
    assert all("tenant_id" in message for message in messages)


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
    forbidden_fragments = ("sk-ant", "lin_api_", "AKIA", "Bearer ")

    for message in messages:
        text = str(message.get("text", ""))
        assert not any(fragment in text for fragment in forbidden_fragments)


def test_hmac_sign_matches_known_sha256() -> None:
    payload = {
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "message_id": "m-1",
        "user_id": "u-1",
        "text": "charged twice",
    }
    signature = hmac_sign(serialize_payload(payload), "secret")
    assert signature == "sha256=9f4c674caf64b290ead19e2c5e540a99805ab409f1990b45b42904caf01de631"
