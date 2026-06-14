"""Webhook secret store tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.secrets_store import WebhookSecretNotFoundError, WebhookSecretStore
from app.tenant_registry import TenantNotFoundError


class _ResultStub:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _SessionStub:
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        self.rows = rows
        self.execute_calls: list[tuple[object, dict[str, object]]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, statement, params: dict[str, object]):
        self.execute_calls.append((statement, params))
        if "set_config('app.current_tenant_id'" in str(statement):
            return _ResultStub(None)
        row = self.rows.pop(0) if self.rows else None
        return _ResultStub(row)


class _SessionFactoryStub:
    def __init__(self, sessions: list[_SessionStub]) -> None:
        self.sessions = sessions

    def __call__(self) -> _SessionStub:
        return self.sessions.pop(0)


@pytest.mark.asyncio
async def test_get_secret_decrypts_ciphertext() -> None:
    key = Fernet.generate_key()
    fernet = Fernet(key)
    tenant_id = uuid4()
    ciphertext = fernet.encrypt(b"secret-a").decode("utf-8")
    session = _SessionStub([{"secret_ciphertext": ciphertext}])
    store = WebhookSecretStore(_SessionFactoryStub([session]), key.decode("utf-8"))

    secret = await store.get_secret(tenant_id)

    assert secret == "secret-a"
    assert len(session.execute_calls) == 2
    assert "set_config('app.current_tenant_id'" in str(session.execute_calls[0][0])
    assert session.execute_calls[0][1] == {"tenant_id": str(tenant_id)}


@pytest.mark.asyncio
async def test_get_secret_raises_when_missing() -> None:
    key = Fernet.generate_key()
    store = WebhookSecretStore(_SessionFactoryStub([_SessionStub([None])]), key.decode("utf-8"))

    with pytest.raises(WebhookSecretNotFoundError):
        await store.get_secret(uuid4())


@pytest.mark.asyncio
async def test_get_secret_by_slug_raises_when_tenant_missing() -> None:
    key = Fernet.generate_key()
    store = WebhookSecretStore(_SessionFactoryStub([_SessionStub([None])]), key.decode("utf-8"))

    with pytest.raises(TenantNotFoundError):
        await store.get_secret_by_slug("unknown")


@pytest.mark.asyncio
async def test_get_secret_by_slug_reads_tenant_then_secret() -> None:
    key = Fernet.generate_key()
    fernet = Fernet(key)
    tenant_id = uuid4()
    slug_session = _SessionStub([{"tenant_id": tenant_id}])
    secret_session = _SessionStub(
        [{"secret_ciphertext": fernet.encrypt(b"secret-b").decode("utf-8")}]
    )
    store = WebhookSecretStore(
        _SessionFactoryStub([slug_session, secret_session]), key.decode("utf-8")
    )

    secret = await store.get_secret_by_slug("tenant-b")

    assert secret == "secret-b"
    assert "set_config('app.current_tenant_id'" in str(secret_session.execute_calls[0][0])
    assert secret_session.execute_calls[0][1] == {"tenant_id": str(tenant_id)}


@pytest.mark.asyncio
async def test_get_secret_by_slug_returns_slug_specific_secret() -> None:
    key = Fernet.generate_key()
    fernet = Fernet(key)
    tenant_a = uuid4()
    tenant_b = uuid4()
    slug_a_session = _SessionStub([{"tenant_id": tenant_a}])
    secret_a_session = _SessionStub(
        [{"secret_ciphertext": fernet.encrypt(b"secret-a").decode("utf-8")}]
    )
    slug_b_session = _SessionStub([{"tenant_id": tenant_b}])
    secret_b_session = _SessionStub(
        [{"secret_ciphertext": fernet.encrypt(b"secret-b").decode("utf-8")}]
    )
    store = WebhookSecretStore(
        _SessionFactoryStub(
            [slug_a_session, secret_a_session, slug_b_session, secret_b_session]
        ),
        key.decode("utf-8"),
    )

    secret_a = await store.get_secret_by_slug("tenant-a")
    secret_b = await store.get_secret_by_slug("tenant-b")

    assert secret_a == "secret-a"
    assert secret_b == "secret-b"
    assert secret_a_session.execute_calls[0][1] == {"tenant_id": str(tenant_a)}
    assert secret_b_session.execute_calls[0][1] == {"tenant_id": str(tenant_b)}
