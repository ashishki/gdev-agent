"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas import AuthTokenRequest, AuthTokenResponse
from app.services.auth_service import (
    AuthService,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
)

router = APIRouter()


def _service_response(result):
    if result.status_code == 200:
        return result.payload
    return JSONResponse(content=result.to_response_body(), status_code=result.status_code)


@router.post("/auth/token", response_model=AuthTokenResponse)
async def create_auth_token(payload: AuthTokenRequest, request: Request):
    """Authenticate a user and issue a JWT."""
    service = AuthService(
        settings=request.app.state.settings,
        db_session_factory=request.app.state.db_session_factory,
        jwt_blocklist_redis=getattr(request.app.state, "jwt_blocklist_redis", None),
    )
    return _service_response(await service.login(payload))


@router.post("/auth/logout", response_model=LogoutResponse)
async def logout(payload: LogoutRequest, request: Request):
    """Revoke the current JWT."""
    service = AuthService(
        settings=request.app.state.settings,
        db_session_factory=request.app.state.db_session_factory,
        jwt_blocklist_redis=getattr(request.app.state, "jwt_blocklist_redis", None),
    )
    return _service_response(await service.logout(payload))


@router.post("/auth/refresh", response_model=AuthTokenResponse)
async def refresh_token(payload: RefreshTokenRequest, request: Request):
    """Rotate the current JWT and return a new access token."""
    service = AuthService(
        settings=request.app.state.settings,
        db_session_factory=request.app.state.db_session_factory,
        jwt_blocklist_redis=getattr(request.app.state, "jwt_blocklist_redis", None),
    )
    return _service_response(await service.refresh_token(payload))
