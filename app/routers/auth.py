"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import AuthTokenRequest, AuthTokenResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/auth/token", response_model=AuthTokenResponse)
async def create_auth_token(payload: AuthTokenRequest, request: Request):
    """Authenticate a user and issue a JWT."""
    service = AuthService(
        settings=request.app.state.settings,
        db_session_factory=request.app.state.db_session_factory,
        jwt_blocklist_redis=getattr(request.app.state, "jwt_blocklist_redis", None),
    )
    return (await service.login(payload)).to_response()
