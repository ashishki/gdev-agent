"""Output guard for draft response safety checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import Settings
from app.schemas import ProposedAction

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-]{20,}"),
    re.compile(r"lin_api_[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9+/=]{20,}"),
]
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


@dataclass
class GuardResult:
    """Output guard scan result."""

    blocked: bool
    redacted_draft: str
    reason: str | None
    action_override: ProposedAction | None = None


class OutputGuard:
    """Applies output secret, URL, and confidence checks."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, draft: str, confidence: float, action: ProposedAction) -> GuardResult:
        """Scan draft output and return optional action override."""
        if not self.settings.output_guard_enabled:
            return GuardResult(blocked=False, redacted_draft=draft, reason=None)

        for pattern in _SECRET_PATTERNS:
            if pattern.search(draft):
                return GuardResult(blocked=True, redacted_draft="", reason="secret pattern matched")

        redacted = draft
        for url in _URL_PATTERN.findall(draft):
            host = (urlparse(url).hostname or "").lower()
            if host in self.settings.url_allowlist:
                continue
            if self.settings.output_url_behavior == "reject":
                return GuardResult(blocked=True, redacted_draft="", reason="disallowed url")
            redacted = redacted.replace(url, "").strip()

        action_override: ProposedAction | None = None
        if confidence < 0.5:
            action_override = action.model_copy(
                update={
                    "tool": "flag_for_human",
                    "risky": True,
                    "risk_reason": "confidence below safety floor",
                }
            )

        return GuardResult(blocked=False, redacted_draft=redacted, reason=None, action_override=action_override)
