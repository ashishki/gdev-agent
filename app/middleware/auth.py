"""JWT authentication middleware."""

from __future__ import annotations

import hashlib
import logging
from typing import Literal
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt  # type: ignore[import-untyped]
from jose.exceptions import ExpiredSignatureError, JWTError  # type: ignore[import-untyped]
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

    class _NoopTracer:
        def start_as_current_span(self, _name: str) -> _NoopSpan:
            return _NoopSpan()

    TRACER = _NoopTracer()


class JWTMiddleware(BaseHTTPMiddleware):
    """Validates JWTs and injects tenant/user context into request.state."""

    def __init__(self, app, settings: Settings | None = None):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        settings = self.settings or request.app.state.settings
        with TRACER.start_as_current_span("middleware.auth") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", request.url.path)
            if (request.method, request.url.path) in {
                ("GET", "/health"),
                ("GET", "/metrics"),
                ("POST", "/webhook"),
                ("POST", "/auth/token"),
            }:
                span.set_attribute("auth.exempt", True)
                return await call_next(request)

            authorization = request.headers.get("Authorization", "")
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer":
                span.set_attribute("auth.valid", False)
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            token = token.strip()
            if not token:
                span.set_attribute("auth.valid", False)
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            try:
                claims = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                )
            except ExpiredSignatureError:
                span.set_attribute("auth.valid", False)
                return JSONResponse(
                    {
                        "error": {
                            "code": "token_expired",
                            "message": "JWT token has expired",
                        }
                    },
                    status_code=401,
                )
            except JWTError:
                span.set_attribute("auth.valid", False)
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            try:
                user_id = UUID(str(claims["sub"]))
                tenant_id = UUID(str(claims["tenant_id"]))
                role = str(claims["role"])
                jti = str(claims["jti"])
            except (KeyError, ValueError, TypeError):
                span.set_attribute("auth.valid", False)
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            span.set_attribute(
                "tenant_id_hash",
                hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:16],
            )

            redis_client = getattr(request.app.state, "jwt_blocklist_redis", None)
            if redis_client is None:
                span.set_attribute("auth.valid", False)
                LOGGER.critical(
                    "jwt blocklist redis unavailable",
                    extra={"event": "jwt_blocklist_unavailable", "context": {}},
                )
                return JSONResponse(
                    {"detail": "Authorization service unavailable"}, status_code=503
                )

            try:
                revoked = await redis_client.get(f"jwt:blocklist:{jti}")
            except Exception:
                span.set_attribute("auth.valid", False)
                LOGGER.critical(
                    "jwt blocklist redis check failed",
                    extra={"event": "jwt_blocklist_check_failed", "context": {}},
                    exc_info=True,
                )
                return JSONResponse(
                    {"detail": "Authorization service unavailable"}, status_code=503
                )

            if revoked:
                span.set_attribute("auth.valid", False)
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            request.state.tenant_id = tenant_id
            request.state.user_id = user_id
            request.state.role = role
            span.set_attribute("auth.valid", True)
            return await call_next(request)
