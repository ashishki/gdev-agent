"""Redis-backed per-user rate limit middleware."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

LOGGER = logging.getLogger(__name__)
try:  # pragma: no cover - optional dependency in minimal local envs
    from opentelemetry import trace  # type: ignore[import-not-found]

    TRACER = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - fallback when opentelemetry is unavailable

    class _NoopSpan:
        def __enter__(self) -> "_NoopSpan":
            return self

        def __exit__(self, exc_type, exc, tb) -> Literal[False]:
            return False

        def set_attribute(self, _name: str, _value: object) -> None:
            return None

        def record_exception(self, _exc: BaseException) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, _name: str, **_kwargs: Any) -> _NoopSpan:
            return _NoopSpan()

    TRACER = _NoopTracer()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-user request cap in a 60s window."""

    def __init__(self, app, settings: Settings | None = None, redis_client=None):
        super().__init__(app)
        self.settings = settings
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        settings = self.settings or request.app.state.settings
        if request.url.path not in {"/webhook", "/auth/token"}:
            return await call_next(request)

        with TRACER.start_as_current_span("middleware.rate_limit") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", request.url.path)
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
            redis_client = self.redis or getattr(
                request.app.state, "jwt_blocklist_redis", None
            )
            if redis_client is None:
                span.set_attribute("rate_limit.bypassed", True)
                LOGGER.warning(
                    "rate limiter unavailable",
                    extra={"event": "rate_limit_bypass", "context": {}},
                )
                return await call_next(request)

            try:
                if request.url.path == "/webhook":
                    user_id = payload.get("user_id")
                    if not user_id:
                        span.set_attribute("rate_limit.user_present", False)
                        return await call_next(request)
                    tenant_id = getattr(request.state, "tenant_id", None)
                    user_hash = hashlib.sha256(
                        str(user_id).encode("utf-8")
                    ).hexdigest()[:16]
                    span.set_attribute("user_id_hash", user_hash)

                    minute_key = self._webhook_key("ratelimit", tenant_id, str(user_id))
                    burst_key = self._webhook_key(
                        "ratelimit_burst", tenant_id, str(user_id)
                    )
                    minute_count = int(await redis_client.incr(minute_key))
                    if minute_count == 1:
                        await redis_client.expire(minute_key, 60)

                    burst_count = int(await redis_client.incr(burst_key))
                    if burst_count == 1:
                        await redis_client.expire(burst_key, 10)

                    if (
                        minute_count > settings.rate_limit_rpm
                        or burst_count > settings.rate_limit_burst
                    ):
                        span.set_attribute("rate_limit.blocked", True)
                        return JSONResponse(
                            {"detail": "Rate limit exceeded"},
                            status_code=429,
                            headers={"Retry-After": "60"},
                        )
                else:
                    email = payload.get("email")
                    if not isinstance(email, str) or not email.strip():
                        span.set_attribute("rate_limit.user_present", False)
                        return await call_next(request)

                    email_hash = hashlib.sha256(
                        email.strip().lower().encode("utf-8")
                    ).hexdigest()[:16]
                    span.set_attribute("email_hash", email_hash)
                    auth_key = f"auth_ratelimit:{email_hash}"
                    auth_count = int(await redis_client.incr(auth_key))
                    if auth_count == 1:
                        await redis_client.expire(auth_key, 60)
                    if auth_count > settings.auth_rate_limit_attempts:
                        span.set_attribute("rate_limit.blocked", True)
                        return JSONResponse(
                            {"detail": "Rate limit exceeded"},
                            status_code=429,
                            headers={"Retry-After": "60"},
                        )
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("rate_limit.bypassed", True)
                LOGGER.warning(
                    "rate limiter unavailable",
                    extra={"event": "rate_limit_bypass", "context": {}},
                )
                return await call_next(request)

            span.set_attribute("rate_limit.blocked", False)
            return await call_next(request)

    @staticmethod
    def _webhook_key(prefix: str, tenant_id: object, user_id: str) -> str:
        # Webhook requests may arrive before auth context exists; isolate those under
        # an explicit anonymous namespace instead of implicitly formatting `None`.
        tenant_prefix = str(tenant_id) if tenant_id is not None else "anonymous"
        return f"{tenant_prefix}:{prefix}:{user_id}"
