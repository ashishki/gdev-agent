"""Authentication routes."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from jose import jwt
from sqlalchemy import text

from app.schemas import AuthTokenRequest, AuthTokenResponse

LOGGER = logging.getLogger(__name__)
router = APIRouter()
_DUMMY_PASSWORD_HASH = b"$2b$12$u6v1GZz.C7Djv7x50j0fAe9s4qjIicqW0ShC0f9f0rYidlnxOS4qm"


@router.post("/auth/token", response_model=AuthTokenResponse)
async def create_auth_token(payload: AuthTokenRequest, request: Request):
    """Authenticate a user and issue a JWT."""
    async with request.app.state.db_session_factory() as session:
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
    email_hash = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()

    if row is None:
        bcrypt.checkpw(candidate_password, _DUMMY_PASSWORD_HASH)
        LOGGER.warning(
            "invalid auth credentials",
            extra={"event": "auth_invalid_credentials", "context": {"email_hash": email_hash}},
        )
        return JSONResponse(
            {"error": {"code": "invalid_credentials", "message": "Invalid email or password"}},
            status_code=401,
        )

    stored_hash = str(row["password_hash"]).encode("utf-8")
    if not bcrypt.checkpw(candidate_password, stored_hash):
        LOGGER.warning(
            "invalid auth credentials",
            extra={"event": "auth_invalid_credentials", "context": {"email_hash": email_hash}},
        )
        return JSONResponse(
            {"error": {"code": "invalid_credentials", "message": "Invalid email or password"}},
            status_code=401,
        )

    settings = request.app.state.settings
    now = datetime.now(UTC)
    expires_in = settings.jwt_token_expiry_hours * 3600
    claims = {
        "sub": str(row["user_id"]),
        "tenant_id": str(row["tenant_id"]),
        "role": str(row["role"]),
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    return AuthTokenResponse(access_token=token, expires_in=expires_in)
