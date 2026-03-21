#!/usr/bin/env python3
"""Run the end-to-end demo flow against a local gdev-agent stack."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
httpx = None


class DemoError(RuntimeError):
    """Raised when the demo flow fails."""


@dataclass(frozen=True)
class DemoConfig:
    base_url: str
    tenant_slug: str
    tenant_id: str
    webhook_secret: str
    admin_email: str
    admin_password: str
    approve_secret: str
    reviewer: str
    poll_interval: float
    timeout_seconds: float


class DemoRunner:
    """Small helper for timed, readable demo output."""

    def __init__(self, config: DemoConfig) -> None:
        client_module = require_httpx()
        self.config = config
        self._started = time.perf_counter()
        self._client = client_module.AsyncClient(
            base_url=config.base_url,
            timeout=client_module.Timeout(10.0, connect=5.0),
        )

    async def __aenter__(self) -> "DemoRunner":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def run(self) -> None:
        self._log("START", f"Base URL {self.config.base_url}")
        await self._step("Health check", self._health_check)
        token = await self._step("Auth token", self._auth_token)
        webhook = await self._step("Send webhook", self._send_webhook)
        pending_id = self._extract_pending_id(webhook)
        await self._step(
            "Wait for pending audit row",
            lambda: self._wait_for_pending_audit(token, webhook["message_id"]),
        )
        approve = await self._step(
            "Approve pending action",
            lambda: self._approve_pending(token, pending_id),
        )
        if approve.get("status") != "approved":
            raise DemoError(f"unexpected approve status: {approve!r}")
        self._log(
            "OK",
            f"Demo completed for pending_id={pending_id} in {self._elapsed():.2f}s",
        )

    async def _step(self, label: str, fn):
        started = time.perf_counter()
        self._log("STEP", label)
        try:
            result = await fn()
        except Exception as exc:
            self._log("FAIL", f"{label} ({time.perf_counter() - started:.2f}s): {exc}")
            raise
        self._log("DONE", f"{label} ({time.perf_counter() - started:.2f}s)")
        return result

    async def _health_check(self) -> dict[str, Any]:
        response = await self._client.get("/health")
        payload = self._expect_json(response, "GET /health")
        if response.status_code != 200:
            raise DemoError(f"health check failed: {payload}")
        return payload

    async def _auth_token(self) -> str:
        response = await self._client.post(
            "/auth/token",
            json={
                "tenant_slug": self.config.tenant_slug,
                "email": self.config.admin_email,
                "password": self.config.admin_password,
            },
        )
        payload = self._expect_json(response, "POST /auth/token")
        if response.status_code != 200:
            raise DemoError(f"auth failed: {payload}")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise DemoError("auth response did not include access_token")
        return token

    async def _send_webhook(self) -> dict[str, Any]:
        message_id = f"demo-{uuid.uuid4().hex[:12]}"
        request_id = f"demo-req-{uuid.uuid4().hex[:12]}"
        body = {
            "request_id": request_id,
            "tenant_id": self.config.tenant_id,
            "message_id": message_id,
            "user_id": "demo-user-42",
            "text": "I was charged twice for my gem pack and need a refund review.",
            "metadata": {"source": "demo.py"},
        }
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        signature = "sha256=" + hmac.new(
            self.config.webhook_secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        response = await self._client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Tenant-Slug": self.config.tenant_slug,
                "X-Webhook-Signature": signature,
            },
        )
        payload = self._expect_json(response, "POST /webhook")
        if response.status_code != 200:
            raise DemoError(f"webhook failed: {payload}")
        if payload.get("status") != "pending":
            raise DemoError(f"webhook did not produce pending state: {payload}")
        payload["message_id"] = message_id
        return payload

    async def _wait_for_pending_audit(self, token: str, message_id: str) -> dict[str, Any]:
        deadline = time.perf_counter() + self.config.timeout_seconds
        headers = {"Authorization": f"Bearer {token}"}

        while time.perf_counter() < deadline:
            response = await self._client.get("/audit", params={"limit": 100}, headers=headers)
            payload = self._expect_json(response, "GET /audit")
            if response.status_code != 200:
                raise DemoError(f"audit lookup failed: {payload}")

            for item in payload.get("data", []):
                if item.get("message_id") == message_id and item.get("status") == "pending":
                    return item

            await asyncio.sleep(self.config.poll_interval)

        raise DemoError(
            f"timed out after {self.config.timeout_seconds:.1f}s waiting for pending audit row"
        )

    async def _approve_pending(self, token: str, pending_id: str) -> dict[str, Any]:
        response = await self._client.post(
            "/approve",
            json={
                "pending_id": pending_id,
                "approved": True,
                "reviewer": self.config.reviewer,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-Approve-Secret": self.config.approve_secret,
            },
        )
        payload = self._expect_json(response, "POST /approve")
        if response.status_code != 200:
            raise DemoError(f"approve failed: {payload}")
        return payload

    @staticmethod
    def _extract_pending_id(payload: dict[str, Any]) -> str:
        pending = payload.get("pending")
        if not isinstance(pending, dict):
            raise DemoError("webhook response missing pending object")
        pending_id = pending.get("pending_id")
        if not isinstance(pending_id, str) or not pending_id:
            raise DemoError("webhook response missing pending_id")
        return pending_id

    @staticmethod
    def _expect_json(response: httpx.Response, label: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DemoError(
                f"{label} returned non-JSON response with status {response.status_code}"
            ) from exc
        if not isinstance(payload, dict):
            raise DemoError(f"{label} returned unexpected JSON payload: {payload!r}")
        return payload

    def _elapsed(self) -> float:
        return time.perf_counter() - self._started

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp} UTC] [{level}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("DEMO_URL", "http://localhost:8000"),
        help="Base URL for the gdev-agent API. Default: %(default)s",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("DEMO_POLL_INTERVAL", "1.0")),
        help="Seconds between audit polling attempts. Default: %(default)s",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("DEMO_TIMEOUT_SECONDS", "30.0")),
        help="Overall poll timeout in seconds. Default: %(default)s",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> DemoConfig:
    return DemoConfig(
        base_url=args.url.rstrip("/"),
        tenant_slug=os.environ.get("DEMO_TENANT_SLUG", "test-tenant-a"),
        tenant_id=os.environ.get(
            "DEMO_TENANT_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        ),
        webhook_secret=os.environ.get(
            "DEMO_WEBHOOK_SECRET", "test-webhook-secret-a"
        ),
        admin_email=os.environ.get("DEMO_ADMIN_EMAIL", "admin-a@example.com"),
        admin_password=os.environ.get("DEMO_ADMIN_PASSWORD", "password123"),
        approve_secret=os.environ.get("DEMO_APPROVE_SECRET", "approve-secret"),
        reviewer=os.environ.get("DEMO_REVIEWER", "demo-runner"),
        poll_interval=args.poll_interval,
        timeout_seconds=args.timeout,
    )


async def _main() -> int:
    args = parse_args()
    config = build_config(args)
    async with DemoRunner(config) as runner:
        await runner.run()
    return 0


def require_httpx():
    global httpx
    if httpx is None:
        try:
            import httpx as httpx_module
        except ModuleNotFoundError as exc:
            raise DemoError(
                "httpx is not installed in this Python environment. "
                "Use the project environment or install dependencies first."
            ) from exc
        httpx = httpx_module
    return httpx


def main() -> int:
    try:
        return asyncio.run(_main())
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except DemoError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        httpx_module = httpx
        if httpx_module is not None and isinstance(exc, httpx_module.HTTPError):
            print(f"HTTP error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
