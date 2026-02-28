"""Redis-backed per-user rate limit middleware."""

from __future__ import annotations

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
        if request.url.path != "/webhook":
            return await call_next(request)

        body = await request.body()
        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        user_id = payload.get("user_id")
        if not user_id:
            return await call_next(request)

        minute_key = f"ratelimit:{user_id}"
        burst_key = f"ratelimit_burst:{user_id}"
        try:
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
        except Exception:
            LOGGER.warning("rate limiter unavailable", extra={"event": "rate_limit_bypass", "context": {}})
            return await call_next(request)

        return await call_next(request)
