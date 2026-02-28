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
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        user_id = payload.get("user_id")
        if not user_id:
            return await call_next(request)

        key = f"ratelimit:{user_id}"
        try:
            count = int(self.redis.incr(key))
            if count == 1:
                self.redis.expire(key, 60)
            if count > self.settings.rate_limit_rpm:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        except Exception:
            LOGGER.warning("rate limiter unavailable", extra={"event": "rate_limit_bypass", "context": {}})
            return await call_next(request)

        return await call_next(request)

