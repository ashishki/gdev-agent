"""HMAC webhook signature verification middleware."""

from __future__ import annotations

import hashlib
import hmac

from fastapi.responses import JSONResponse

from app.config import Settings
from app.secrets_store import WebhookSecretNotFoundError
from app.tenant_registry import TenantNotFoundError


class SignatureMiddleware:
    """Validates webhook signatures using per-tenant secrets."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/webhook":
            await self.app(scope, receive, send)
            return

        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

        async def empty_receive():
            return {"type": "http.disconnect"}

        tenant_slug = headers.get("x-tenant-slug")
        if not tenant_slug:
            await JSONResponse({"detail": "Missing X-Tenant-Slug header"}, status_code=400)(scope, empty_receive, send)
            return

        secret_store = getattr(scope["app"].state, "webhook_secret_store", None)
        if secret_store is None:
            await JSONResponse({"detail": "Signature verification unavailable"}, status_code=503)(
                scope,
                empty_receive,
                send,
            )
            return
        try:
            webhook_secret = await secret_store.get_secret_by_slug(tenant_slug)
        except (TenantNotFoundError, WebhookSecretNotFoundError):
            await JSONResponse({"detail": "Invalid signature"}, status_code=401)(scope, empty_receive, send)
            return
        expected = "sha256=" + hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        received = headers.get("x-webhook-signature", "")
        if not hmac.compare_digest(expected, received):
            await JSONResponse({"detail": "Invalid signature"}, status_code=401)(scope, empty_receive, send)
            return

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)
