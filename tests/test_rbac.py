"""RBAC tests for role enforcement on /approve."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.config import Settings
from app.schemas import ApproveRequest


def _approve_role_dependency():
    route = next(
        r
        for r in main.app.router.routes
        if getattr(r, "path", None) == "/approve" and "POST" in getattr(r, "methods", set())
    )
    dependencies = route.dependant.dependencies
    assert dependencies, "Expected at least one dependency on /approve"
    return dependencies[0].call


def test_viewer_role_cannot_call_approve() -> None:
    dependency = _approve_role_dependency()
    request = SimpleNamespace(state=SimpleNamespace(role="viewer"))
    with pytest.raises(HTTPException) as exc:
        dependency(request)
    assert exc.value.status_code == 403


def test_support_agent_role_can_call_approve() -> None:
    dependency = _approve_role_dependency()
    dependency(SimpleNamespace(state=SimpleNamespace(role="support_agent")))

    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="approve-secret")
    main.app.state.agent = SimpleNamespace(
        approve=lambda _payload, jwt_tenant_id=None: {
            "status": "approved",
            "pending_id": "p1",
            "result": {"ok": True},
        }
    )
    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(
            headers={"X-Approve-Secret": "approve-secret"},
            state=SimpleNamespace(tenant_id="tenant-a"),
        ),
    )
    assert response["status"] == "approved"


def test_tenant_admin_role_can_call_approve() -> None:
    dependency = _approve_role_dependency()
    dependency(SimpleNamespace(state=SimpleNamespace(role="tenant_admin")))

    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="approve-secret")
    main.app.state.agent = SimpleNamespace(
        approve=lambda _payload, jwt_tenant_id=None: {
            "status": "approved",
            "pending_id": "p1",
            "result": {"ok": True},
        }
    )
    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(
            headers={"X-Approve-Secret": "approve-secret"},
            state=SimpleNamespace(tenant_id="tenant-a"),
        ),
    )
    assert response["status"] == "approved"
