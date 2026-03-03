"""JWT authentication middleware."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

LOGGER = logging.getLogger(__name__)


class JWTMiddleware(BaseHTTPMiddleware):
    """Validates JWTs and injects tenant/user context into request.state."""

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if (request.method, request.url.path) in {("GET", "/health"), ("POST", "/webhook")}:
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        token = authorization[len("Bearer ") :].strip()
        if not token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except ExpiredSignatureError:
            return JSONResponse(
                {"error": {"code": "token_expired", "message": "JWT token has expired"}},
                status_code=401,
            )
        except JWTError:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        try:
            user_id = UUID(str(claims["sub"]))
            tenant_id = UUID(str(claims["tenant_id"]))
            role = str(claims["role"])
            jti = str(claims["jti"])
        except (KeyError, ValueError, TypeError):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        redis_client = getattr(request.app.state, "jwt_blocklist_redis", None)
        if redis_client is None:
            LOGGER.critical(
                "jwt blocklist redis unavailable",
                extra={"event": "jwt_blocklist_unavailable", "context": {}},
            )
            return JSONResponse({"detail": "Authorization service unavailable"}, status_code=503)

        try:
            revoked = await redis_client.get(f"jwt:blocklist:{jti}")
        except Exception:
            LOGGER.critical(
                "jwt blocklist redis check failed",
                extra={"event": "jwt_blocklist_check_failed", "context": {}},
                exc_info=True,
            )
            return JSONResponse({"detail": "Authorization service unavailable"}, status_code=503)

        if revoked:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.tenant_id = tenant_id
        request.state.user_id = user_id
        request.state.role = role
        return await call_next(request)
