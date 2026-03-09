"""Scenario A burst user profile."""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

from load_tests.locustfile import hmac_sign, load_sample_messages, serialize_payload

SAMPLE_MESSAGES = load_sample_messages()


class BurstUser(HttpUser):
    """Burst profile: high webhook ratio with occasional approve/read."""

    scenario_name = "burst"
    wait_time = between(0.016, 0.02)

    @task(8)
    def post_webhook(self) -> None:
        payload = random.choice(SAMPLE_MESSAGES).copy()
        payload["message_id"] = f"burst-{uuid.uuid4().hex}"
        payload["tenant_id"] = os.getenv(
            "LOAD_TEST_TENANT_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        )
        body = serialize_payload(payload)
        webhook_secret = os.getenv("LOAD_TEST_WEBHOOK_SECRET", "test-webhook-secret")
        tenant_slug = os.getenv("LOAD_TEST_TENANT_SLUG", "test-tenant-a")
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-Slug": tenant_slug,
            "X-Webhook-Signature": hmac_sign(body, webhook_secret),
            "X-Request-ID": uuid.uuid4().hex,
        }
        self.client.post("/webhook", data=body, headers=headers, name="POST /webhook")

    @task(1)
    def post_approve(self) -> None:
        token = os.getenv("LOAD_TEST_BEARER_TOKEN", "")
        if not token:
            return
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        approve_secret = os.getenv("LOAD_TEST_APPROVE_SECRET", "")
        if approve_secret:
            headers["X-Approve-Secret"] = approve_secret
        self.client.post(
            "/approve",
            json={"pending_id": uuid.uuid4().hex, "approved": True, "reviewer": "load"},
            headers=headers,
            name="POST /approve",
        )

    @task(1)
    def get_tickets(self) -> None:
        token = os.getenv("LOAD_TEST_BEARER_TOKEN", "")
        if not token:
            return
        self.client.get(
            "/tickets",
            headers={"Authorization": f"Bearer {token}"},
            name="GET /tickets",
        )
