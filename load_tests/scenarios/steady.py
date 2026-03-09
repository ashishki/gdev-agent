"""Scenario B steady-state user profile."""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

from load_tests.locustfile import hmac_sign, load_sample_messages, serialize_payload

SAMPLE_MESSAGES = load_sample_messages()


class SteadyUser(HttpUser):
    """Steady profile: lower webhook pressure, more read traffic."""

    scenario_name = "steady"
    wait_time = between(0.08, 0.2)

    @task(7)
    def post_webhook(self) -> None:
        payload = random.choice(SAMPLE_MESSAGES).copy()
        payload["message_id"] = f"steady-{uuid.uuid4().hex}"
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

    @task(2)
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
    def get_reads(self) -> None:
        token = os.getenv("LOAD_TEST_BEARER_TOKEN", "")
        if not token:
            return
        headers = {"Authorization": f"Bearer {token}"}
        endpoint = random.choice(["/tickets", "/clusters", "/eval/runs"])
        self.client.get(endpoint, headers=headers, name=f"GET {endpoint}")
