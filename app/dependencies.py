"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request


def require_role(*roles: str):
    """Require one of the specified JWT roles on the current request."""

    def dependency(request: Request) -> None:
        if getattr(request.state, "role", None) not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")

    return Depends(dependency)
