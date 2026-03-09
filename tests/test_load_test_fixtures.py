"""Load test fixture and HMAC utility tests."""

from __future__ import annotations

from pathlib import Path

from load_tests.locustfile import hmac_sign, load_sample_messages, serialize_payload


def test_sample_messages_jsonl_parses() -> None:
    fixture_path = Path("load_tests/fixtures/sample_messages.jsonl")
    messages = load_sample_messages(fixture_path)

    assert len(messages) == 50
    assert all("text" in message for message in messages)
    assert all("tenant_id" in message for message in messages)


def test_hmac_sign_matches_known_sha256() -> None:
    payload = {
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "message_id": "m-1",
        "user_id": "u-1",
        "text": "charged twice",
    }
    signature = hmac_sign(serialize_payload(payload), "secret")
    assert (
        signature
        == "sha256=9f4c674caf64b290ead19e2c5e540a99805ab409f1990b45b42904caf01de631"
    )
