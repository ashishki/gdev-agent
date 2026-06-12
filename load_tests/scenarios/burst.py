"""Scenario A burst user profile."""

from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, task

from load_tests.locustfile import (
    build_webhook_request,
    load_sample_messages,
    record_kpi,
    scenario_from_environment,
    simulate_provider_latency,
)

SAMPLE_MESSAGES = load_sample_messages()


class BurstUser(HttpUser):
    """Burst profile: high webhook ratio with occasional approve/read."""

    scenario_name = "burst"
    wait_time = between(0.016, 0.02)

    @task(8)
    def post_webhook(self) -> None:
        config = scenario_from_environment(self.environment)
        simulate_provider_latency(self.environment, config)
        body, headers, _payload = build_webhook_request(
            SAMPLE_MESSAGES, config, request_prefix="burst"
        )
        with self.client.post(
            "/webhook",
            data=body,
            headers=headers,
            name="POST /webhook",
            catch_response=True,
        ) as response:
            if response.status_code == 400:
                record_kpi(self.environment, "guard_block")
            if config.duplicate_replay:
                record_kpi(self.environment, "dedup_hit_expected")
            try:
                data = response.json()
            except ValueError:
                return
            if data.get("status") == "pending":
                record_kpi(self.environment, "pending_approval")

    @task(1)
    def post_approve(self) -> None:
        token = os.getenv("LOAD_TEST_BEARER_TOKEN", "")
        if not token:
            return
        headers = {"Authorization": " ".join(("Bearer", token)), "Content-Type": "application/json"}
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
            headers={"Authorization": " ".join(("Bearer", token))},
            name="GET /tickets",
        )
