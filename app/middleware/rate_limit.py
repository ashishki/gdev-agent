"""Redis-backed per-user rate limit middleware."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

LOGGER = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-user request cap in a 60s window."""

    def __init__(self, app, settings: Settings, redis_client):
        super().__init__(app)
        self.settings = settings
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in {"/webhook", "/auth/token"}:
            return await call_next(request)

        body = await request.body()
        body_sent = False

        async def _receive():
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        try:
            if request.url.path == "/webhook":
                user_id = payload.get("user_id")
                if not user_id:
                    return await call_next(request)

                minute_key = f"ratelimit:{user_id}"
                burst_key = f"ratelimit_burst:{user_id}"
                minute_count = int(self.redis.incr(minute_key))
                if minute_count == 1:
                    self.redis.expire(minute_key, 60)

                burst_count = int(self.redis.incr(burst_key))
                if burst_count == 1:
                    self.redis.expire(burst_key, 10)

                if minute_count > self.settings.rate_limit_rpm or burst_count > self.settings.rate_limit_burst:
                    return JSONResponse(
                        {"detail": "Rate limit exceeded"},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
            else:
                email = payload.get("email")
                if not isinstance(email, str) or not email.strip():
                    return await call_next(request)

                email_hash = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]
                auth_key = f"auth_ratelimit:{email_hash}"
                auth_count = int(self.redis.incr(auth_key))
                if auth_count == 1:
                    self.redis.expire(auth_key, 60)
                if auth_count > self.settings.auth_rate_limit_attempts:
                    return JSONResponse(
                        {"detail": "Rate limit exceeded"},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
        except Exception:
            LOGGER.warning("rate limiter unavailable", extra={"event": "rate_limit_bypass", "context": {}})
            return await call_next(request)

        return await call_next(request)
