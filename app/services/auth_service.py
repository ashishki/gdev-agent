"""Authentication service layer."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Literal
from uuid import uuid4

import bcrypt
from jose import jwt  # type: ignore[import-untyped]
from jose.exceptions import ExpiredSignatureError, JWTError  # type: ignore[import-untyped]
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
from sqlalchemy import text

from app.config import Settings
from app.schemas import AuthTokenRequest, AuthTokenResponse, ErrorDetail, ErrorResponse
from app.tracing import get_tracer

UTC = timezone.utc

LOGGER = logging.getLogger(__name__)
_DUMMY_PASSWORD_HASH = b"$2b$12$u6v1GZz.C7Djv7x50j0fAe9s4qjIicqW0ShC0f9f0rYidlnxOS4qm"
AUTH_SERVICE_CALLS_TOTAL = Counter(
    "gdev_auth_service_calls_total",
    "Auth service method calls by outcome",
    ["method", "outcome"],
)
AUTH_SERVICE_DURATION_SECONDS = Histogram(
    "gdev_auth_service_duration_seconds",
    "Auth service method latency",
    ["method"],
)
TRACER = get_tracer(__name__)


class LogoutRequest(BaseModel):
    """Logout payload containing the current bearer token."""

    access_token: str


class LogoutResponse(BaseModel):
    """Logout response payload."""

    status: Literal["revoked"] = "revoked"


class RefreshTokenRequest(BaseModel):
    """Refresh payload containing the current bearer token."""

    access_token: str


class _ServiceResult(BaseModel):
    status_code: int
    payload: BaseModel

    def to_response_body(self) -> dict[str, object]:
        return self.payload.model_dump(mode="json")


class LoginResult(_ServiceResult):
    payload: AuthTokenResponse | ErrorResponse


class LogoutResult(_ServiceResult):
    payload: LogoutResponse | ErrorResponse


class RefreshTokenResult(_ServiceResult):
    payload: AuthTokenResponse | ErrorResponse


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class AuthService:
    """Business logic for auth endpoints."""

    def __init__(self, *, settings: Settings, db_session_factory, jwt_blocklist_redis) -> None:
        self._settings = settings
        self._db_session_factory = db_session_factory
        self._jwt_blocklist_redis = jwt_blocklist_redis

    async def login(self, payload: AuthTokenRequest) -> LoginResult:
        started_at = perf_counter()
        email_hash = _sha256_short(payload.email.strip().lower())

        with TRACER.start_as_current_span("service.auth.login") as span:
            span.set_attribute("email_hash", email_hash)
            try:
                async with self._db_session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            text(
                                """
                                SELECT set_config(
                                    'app.current_tenant_id',
                                    (
                                        SELECT tenant_id::text
                                        FROM tenants
                                        WHERE slug = :tenant_slug AND is_active = TRUE
                                        LIMIT 1
                                    ),
                                    TRUE
                                )
                                """
                            ),
                            {"tenant_slug": payload.tenant_slug},
                        )
                        result = await session.execute(
                            text(
                                """
                                SELECT user_id, tenant_id, role, password_hash
                                FROM tenant_users
                                WHERE lower(email) = lower(:email) AND is_active = TRUE
                                LIMIT 1
                                """
                            ),
                            {"email": payload.email},
                        )
                        row = result.mappings().first()

                candidate_password = payload.password.encode("utf-8")
                if row is None:
                    bcrypt.checkpw(candidate_password, _DUMMY_PASSWORD_HASH)
                    return self._login_invalid_result(email_hash)

                stored_hash = str(row["password_hash"]).encode("utf-8")
                if not bcrypt.checkpw(candidate_password, stored_hash):
                    return self._login_invalid_result(email_hash)

                tenant_hash = _sha256_short(str(row["tenant_id"]))
                span.set_attribute("tenant_id_hash", tenant_hash)
                now = datetime.now(UTC)
                expires_in = self._settings.jwt_token_expiry_hours * 3600
                claims = {
                    "sub": str(row["user_id"]),
                    "tenant_id": str(row["tenant_id"]),
                    "role": str(row["role"]),
                    "jti": str(uuid4()),
                    "iat": int(now.timestamp()),
                    "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
                }
                token = jwt.encode(
                    claims,
                    self._settings.jwt_secret,
                    algorithm=self._settings.jwt_algorithm,
                )
                AUTH_SERVICE_CALLS_TOTAL.labels(method="login", outcome="success").inc()
                LOGGER.info(
                    "auth login completed",
                    extra={
                        "event": "auth_login_completed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                )
                return LoginResult(
                    status_code=200,
                    payload=AuthTokenResponse(access_token=token, expires_in=expires_in),
                )
            except Exception as exc:
                span.record_exception(exc)
                AUTH_SERVICE_CALLS_TOTAL.labels(method="login", outcome="error").inc()
                LOGGER.error(
                    "auth login failed",
                    extra={
                        "event": "auth_login_failed",
                        "context": {"email_hash": email_hash},
                    },
                    exc_info=True,
                )
                raise
            finally:
                AUTH_SERVICE_DURATION_SECONDS.labels(method="login").observe(
                    perf_counter() - started_at
                )

    async def logout(self, payload: LogoutRequest) -> LogoutResult:
        started_at = perf_counter()

        with TRACER.start_as_current_span("service.auth.logout") as span:
            try:
                claims = self._decode_token(payload.access_token)
                tenant_hash = _sha256_short(str(claims["tenant_id"]))
                span.set_attribute("tenant_id_hash", tenant_hash)
                ttl_seconds = self._ttl_seconds(int(str(claims["exp"])))
                await self._store_revoked_token(str(claims["jti"]), ttl_seconds)
                AUTH_SERVICE_CALLS_TOTAL.labels(method="logout", outcome="success").inc()
                LOGGER.info(
                    "auth logout completed",
                    extra={
                        "event": "auth_logout_completed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                )
                return LogoutResult(status_code=200, payload=LogoutResponse())
            except ExpiredSignatureError:
                AUTH_SERVICE_CALLS_TOTAL.labels(method="logout", outcome="token_expired").inc()
                return LogoutResult(
                    status_code=401,
                    payload=ErrorResponse(
                        error=ErrorDetail(
                            code="token_expired",
                            message="JWT token has expired",
                        )
                    ),
                )
            except JWTError:
                AUTH_SERVICE_CALLS_TOTAL.labels(method="logout", outcome="invalid_token").inc()
                return LogoutResult(
                    status_code=401,
                    payload=ErrorResponse(
                        error=ErrorDetail(
                            code="invalid_token",
                            message="Invalid access token",
                        )
                    ),
                )
            except Exception as exc:
                span.record_exception(exc)
                AUTH_SERVICE_CALLS_TOTAL.labels(method="logout", outcome="error").inc()
                LOGGER.error(
                    "auth logout failed",
                    extra={"event": "auth_logout_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                AUTH_SERVICE_DURATION_SECONDS.labels(method="logout").observe(
                    perf_counter() - started_at
                )

    async def refresh_token(self, payload: RefreshTokenRequest) -> RefreshTokenResult:
        started_at = perf_counter()

        with TRACER.start_as_current_span("service.auth.refresh_token") as span:
            try:
                claims = self._decode_token(payload.access_token)
                tenant_hash = _sha256_short(str(claims["tenant_id"]))
                span.set_attribute("tenant_id_hash", tenant_hash)
                await self._ensure_token_not_revoked(str(claims["jti"]))
                await self._store_revoked_token(
                    str(claims["jti"]),
                    self._ttl_seconds(int(str(claims["exp"]))),
                )

                now = datetime.now(UTC)
                expires_in = self._settings.jwt_token_expiry_hours * 3600
                refreshed_claims = {
                    "sub": str(claims["sub"]),
                    "tenant_id": str(claims["tenant_id"]),
                    "role": str(claims["role"]),
                    "jti": str(uuid4()),
                    "iat": int(now.timestamp()),
                    "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
                }
                token = jwt.encode(
                    refreshed_claims,
                    self._settings.jwt_secret,
                    algorithm=self._settings.jwt_algorithm,
                )
                AUTH_SERVICE_CALLS_TOTAL.labels(
                    method="refresh_token",
                    outcome="success",
                ).inc()
                LOGGER.info(
                    "auth refresh completed",
                    extra={
                        "event": "auth_refresh_completed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                )
                return RefreshTokenResult(
                    status_code=200,
                    payload=AuthTokenResponse(access_token=token, expires_in=expires_in),
                )
            except ExpiredSignatureError:
                AUTH_SERVICE_CALLS_TOTAL.labels(
                    method="refresh_token",
                    outcome="token_expired",
                ).inc()
                return RefreshTokenResult(
                    status_code=401,
                    payload=ErrorResponse(
                        error=ErrorDetail(
                            code="token_expired",
                            message="JWT token has expired",
                        )
                    ),
                )
            except JWTError:
                AUTH_SERVICE_CALLS_TOTAL.labels(
                    method="refresh_token",
                    outcome="invalid_token",
                ).inc()
                return RefreshTokenResult(
                    status_code=401,
                    payload=ErrorResponse(
                        error=ErrorDetail(
                            code="invalid_token",
                            message="Invalid access token",
                        )
                    ),
                )
            except Exception as exc:
                span.record_exception(exc)
                AUTH_SERVICE_CALLS_TOTAL.labels(method="refresh_token", outcome="error").inc()
                LOGGER.error(
                    "auth refresh failed",
                    extra={"event": "auth_refresh_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                AUTH_SERVICE_DURATION_SECONDS.labels(method="refresh_token").observe(
                    perf_counter() - started_at
                )

    async def _store_revoked_token(self, jti: str, ttl_seconds: int) -> None:
        if self._jwt_blocklist_redis is None:
            raise RuntimeError("JWT blocklist redis is unavailable")
        await self._jwt_blocklist_redis.set(f"jwt:blocklist:{jti}", "1", ex=ttl_seconds)

    async def _ensure_token_not_revoked(self, jti: str) -> None:
        if self._jwt_blocklist_redis is None:
            raise RuntimeError("JWT blocklist redis is unavailable")
        revoked = await self._jwt_blocklist_redis.get(f"jwt:blocklist:{jti}")
        if revoked:
            raise JWTError("Token already revoked")

    def _decode_token(self, access_token: str) -> dict[str, object]:
        return jwt.decode(
            access_token,
            self._settings.jwt_secret,
            algorithms=[self._settings.jwt_algorithm],
        )

    @staticmethod
    def _ttl_seconds(exp_timestamp: int) -> int:
        remaining = exp_timestamp - int(datetime.now(UTC).timestamp())
        return max(remaining, 1)

    @staticmethod
    def _login_invalid_result(email_hash: str) -> LoginResult:
        AUTH_SERVICE_CALLS_TOTAL.labels(method="login", outcome="invalid_credentials").inc()
        LOGGER.warning(
            "invalid auth credentials",
            extra={
                "event": "auth_invalid_credentials",
                "context": {"email_hash": email_hash},
            },
        )
        return LoginResult(
            status_code=401,
            payload=ErrorResponse(
                error=ErrorDetail(
                    code="invalid_credentials",
                    message="Invalid email or password",
                )
            ),
        )
