"""HMAC webhook signature verification middleware."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings


class SignatureMiddleware(BaseHTTPMiddleware):
    """Validates webhook signatures when WEBHOOK_SECRET is set."""

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if not self.settings.webhook_secret:
            return await call_next(request)
        if request.url.path != "/webhook":
            return await call_next(request)

        body = await request.body()

        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        expected = "sha256=" + hmac.new(
            self.settings.webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        received = request.headers.get("X-Webhook-Signature", "")
        if not hmac.compare_digest(expected, received):
            return JSONResponse({"detail": "Invalid signature"}, status_code=401)
        return await call_next(request)
