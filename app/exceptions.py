"""Domain exceptions for service-layer failures."""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base domain exception with HTTP mapping metadata."""

    def __init__(self, detail: Any, status_code: int = 500) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class BudgetError(AgentError):
    """Raised when tenant budget is exhausted."""

    def __init__(self, detail: Any | None = None) -> None:
        super().__init__(
            detail=detail or {"error": {"code": "budget_exhausted"}},
            status_code=429,
        )


class ValidationError(AgentError):
    """Raised when inbound agent input is invalid."""

    def __init__(self, detail: Any, status_code: int = 400) -> None:
        super().__init__(detail=detail, status_code=status_code)
