"""Unit tests for AuthService."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from prometheus_client import REGISTRY

from app.config import Settings
from app.schemas import AuthTokenRequest, AuthTokenResponse
from app.services import auth_service as auth_service_module
from app.services.auth_service import (
    AuthService,
    LogoutRequest,
    RefreshTokenRequest,
)


@dataclass
class _RecordedSpan:
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    exceptions: list[BaseException] = field(default_factory=list)

    def __enter__(self) -> "_RecordedSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordedSpan] = []

    def start_as_current_span(self, name: str) -> _RecordedSpan:
        span = _RecordedSpan(name=name)
        self.spans.append(span)
        return span


class _ResultStub:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _SessionStub:
    def __init__(
        self,
        row: dict[str, object] | None,
        execute_calls: list[tuple[str, dict[str, object]]],
        known_tenant_slug: str = "tenant-a",
    ) -> None:
        self._row = row
        self._execute_calls = execute_calls
        self._known_tenant_slug = known_tenant_slug
        self._tenant_context_valid = False

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self) -> "_SessionStub":
        return self

    async def execute(self, statement, params):
        self._execute_calls.append((str(statement), params))
        sql = str(statement).lower()
        if "set_config(" in sql:
            self._tenant_context_valid = (
                params.get("tenant_slug") == self._known_tenant_slug
            )
            return _ResultStub({"set_config": "ok"})
        if "from tenant_users" in sql and self._tenant_context_valid:
            return _ResultStub(self._row)
        return _ResultStub(None)


class _SessionFactoryStub:
    def __init__(
        self,
        row: dict[str, object] | None,
        *,
        known_tenant_slug: str = "tenant-a",
    ) -> None:
        self._row = row
        self._known_tenant_slug = known_tenant_slug
        self.execute_calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self) -> _SessionStub:
        return _SessionStub(self._row, self.execute_calls, self._known_tenant_slug)


class _AsyncRedisStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.set_calls.append((key, value, ex))
        return True


def _metric_value(method: str, outcome: str) -> float:
    value = REGISTRY.get_sample_value(
        "gdev_auth_service_calls_total",
        labels={"method": method, "outcome": outcome},
    )
    return float(value) if value is not None else 0.0


def _token(
    settings: Settings, *, tenant_id: str, user_id: str, role: str, jti: str
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_login_returns_token_and_records_observability(monkeypatch) -> None:
    tracer = _RecordingTracer()
    settings = Settings(jwt_secret="x" * 32, jwt_token_expiry_hours=8)
    user_id = str(uuid4())
    tenant_id = str(uuid4())
    before = _metric_value("login", "success")
    monkeypatch.setattr(auth_service_module, "TRACER", tracer)
    monkeypatch.setattr(auth_service_module.bcrypt, "checkpw", lambda *_: True)
    service = AuthService(
        settings=settings,
        db_session_factory=_SessionFactoryStub(
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": "support_agent",
                "password_hash": "stored-hash",
            }
        ),
        jwt_blocklist_redis=_AsyncRedisStub(),
    )

    result = await service.login(
        AuthTokenRequest(
            tenant_slug="tenant-a",
            email="agent@example.com",
            password="s3cret!",
        )
    )

    assert result.status_code == 200
    assert isinstance(result.payload, AuthTokenResponse)
    claims = jwt.decode(
        result.payload.access_token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["sub"] == user_id
    assert claims["tenant_id"] == tenant_id
    assert claims["role"] == "support_agent"
    assert _metric_value("login", "success") == before + 1
    assert tracer.spans[0].name == "service.auth.login"
    assert (
        tracer.spans[0].attributes["tenant_id_hash"]
        == hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    )


@pytest.mark.asyncio
async def test_login_invalid_credentials_returns_401_and_increments_counter(
    monkeypatch,
) -> None:
    tracer = _RecordingTracer()
    before = _metric_value("login", "invalid_credentials")
    monkeypatch.setattr(auth_service_module, "TRACER", tracer)
    monkeypatch.setattr(auth_service_module.bcrypt, "checkpw", lambda *_: False)
    service = AuthService(
        settings=Settings(jwt_secret="x" * 32),
        db_session_factory=_SessionFactoryStub(None),
        jwt_blocklist_redis=_AsyncRedisStub(),
    )

    result = await service.login(
        AuthTokenRequest(
            tenant_slug="tenant-a",
            email="missing@example.com",
            password="pw",
        )
    )

    assert result.status_code == 401
    assert result.payload.model_dump() == {
        "error": {
            "code": "invalid_credentials",
            "message": "Invalid email or password",
        }
    }
    assert _metric_value("login", "invalid_credentials") == before + 1
    assert tracer.spans[0].name == "service.auth.login"


@pytest.mark.asyncio
async def test_logout_revokes_token_and_records_span(monkeypatch) -> None:
    tracer = _RecordingTracer()
    settings = Settings(jwt_secret="x" * 32)
    tenant_id = str(uuid4())
    jti = str(uuid4())
    before = _metric_value("logout", "success")
    redis_stub = _AsyncRedisStub()
    monkeypatch.setattr(auth_service_module, "TRACER", tracer)
    service = AuthService(
        settings=settings,
        db_session_factory=_SessionFactoryStub(None),
        jwt_blocklist_redis=redis_stub,
    )

    result = await service.logout(
        LogoutRequest(
            access_token=_token(
                settings,
                tenant_id=tenant_id,
                user_id=str(uuid4()),
                role="viewer",
                jti=jti,
            )
        )
    )

    assert result.status_code == 200
    assert result.payload.model_dump() == {"status": "revoked"}
    assert redis_stub.set_calls[0][0] == f"jwt:blocklist:{jti}"
    assert _metric_value("logout", "success") == before + 1
    assert tracer.spans[0].name == "service.auth.logout"
    assert (
        tracer.spans[0].attributes["tenant_id_hash"]
        == hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    )


@pytest.mark.asyncio
async def test_refresh_token_rotates_jti_and_revokes_previous_token(
    monkeypatch,
) -> None:
    tracer = _RecordingTracer()
    settings = Settings(jwt_secret="x" * 32, jwt_token_expiry_hours=8)
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    old_jti = str(uuid4())
    before = _metric_value("refresh_token", "success")
    redis_stub = _AsyncRedisStub()
    monkeypatch.setattr(auth_service_module, "TRACER", tracer)
    service = AuthService(
        settings=settings,
        db_session_factory=_SessionFactoryStub(None),
        jwt_blocklist_redis=redis_stub,
    )

    result = await service.refresh_token(
        RefreshTokenRequest(
            access_token=_token(
                settings,
                tenant_id=tenant_id,
                user_id=user_id,
                role="tenant_admin",
                jti=old_jti,
            )
        )
    )

    assert result.status_code == 200
    assert isinstance(result.payload, AuthTokenResponse)
    claims = jwt.decode(
        result.payload.access_token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["sub"] == user_id
    assert claims["tenant_id"] == tenant_id
    assert claims["role"] == "tenant_admin"
    assert claims["jti"] != old_jti
    assert redis_stub.set_calls[0][0] == f"jwt:blocklist:{old_jti}"
    assert _metric_value("refresh_token", "success") == before + 1
    assert tracer.spans[0].name == "service.auth.refresh_token"
    assert (
        tracer.spans[0].attributes["tenant_id_hash"]
        == hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    )
