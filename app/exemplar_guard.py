"""Curated-example consistency guard for triage routing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, cast, get_args

from app.config import Settings
from app.schemas import (
    Category,
    ClassificationResult,
    ExemplarConsistencyResult,
    ExemplarMatch,
    ProposedAction,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_EXEMPLAR_PATH = Path(__file__).resolve().parents[1] / "eval" / "exemplars" / "triage_v1.jsonl"
WORD_RE = re.compile(r"[a-z0-9]+")
VALID_CATEGORIES = set(get_args(Category))


@dataclass(frozen=True)
class TriageExemplar:
    """Curated synthetic example for runtime consistency checks."""

    exemplar_id: str
    text: str
    category: Category
    requires_human: bool


DEFAULT_EXEMPLARS: tuple[TriageExemplar, ...] = (
    TriageExemplar(
        exemplar_id="billing-refund-001",
        text="I was charged twice for the starter pack and need a refund review.",
        category="billing",
        requires_human=True,
    ),
    TriageExemplar(
        exemplar_id="billing-refund-002",
        text="Refund my accidental gems purchase from yesterday.",
        category="billing",
        requires_human=True,
    ),
    TriageExemplar(
        exemplar_id="account-access-001",
        text="My verification code never arrives and I am locked out.",
        category="account_access",
        requires_human=True,
    ),
    TriageExemplar(
        exemplar_id="moderation-001",
        text="A player is repeatedly harassing others in chat.",
        category="moderation",
        requires_human=True,
    ),
    TriageExemplar(
        exemplar_id="legal-privacy-001",
        text="Please delete the records for this profile under privacy rights.",
        category="legal",
        requires_human=True,
    ),
    TriageExemplar(
        exemplar_id="bug-report-001",
        text="Game crashes with ERR-0001 on Windows after match start.",
        category="bug_report",
        requires_human=False,
    ),
    TriageExemplar(
        exemplar_id="bug-report-002",
        text="The export button creates an empty CSV for the synthetic project.",
        category="bug_report",
        requires_human=False,
    ),
    TriageExemplar(
        exemplar_id="gameplay-question-001",
        text="How do I craft a healing potion in the tutorial area?",
        category="gameplay_question",
        requires_human=False,
    ),
)


class ExemplarConsistencyGuard:
    """Compare a new triage decision against curated synthetic examples."""

    def __init__(self, settings: Settings, exemplars: Iterable[TriageExemplar] | None = None) -> None:
        self.enabled = settings.exemplar_guard_enabled
        self.threshold = settings.exemplar_guard_threshold
        self.top_k = max(1, settings.exemplar_guard_top_k)
        self.exemplars = tuple(exemplars) if exemplars is not None else self._load_exemplars(settings)

    def evaluate(
        self,
        *,
        text: str,
        classification: ClassificationResult,
        action: ProposedAction,
    ) -> ExemplarConsistencyResult:
        """Return a non-authoritative consistency signal for the proposed route."""
        if not self.enabled:
            return ExemplarConsistencyResult(status="disabled", threshold=self.threshold)

        matches = self._nearest_matches(text)
        if not matches:
            return ExemplarConsistencyResult(status="no_match", threshold=self.threshold)

        conflict_reason = self._conflict_reason(matches[0], classification, action)
        if conflict_reason is not None:
            return ExemplarConsistencyResult(
                status="conflict",
                threshold=self.threshold,
                matches=matches,
                reason=conflict_reason,
            )
        return ExemplarConsistencyResult(
            status="consistent",
            threshold=self.threshold,
            matches=matches,
        )

    def _nearest_matches(self, text: str) -> list[ExemplarMatch]:
        scored: list[ExemplarMatch] = []
        for exemplar in self.exemplars:
            similarity = _similarity(text, exemplar.text)
            if similarity >= self.threshold:
                scored.append(
                    ExemplarMatch(
                        exemplar_id=exemplar.exemplar_id,
                        category=exemplar.category,
                        requires_human=exemplar.requires_human,
                        similarity=round(similarity, 4),
                    )
                )
        scored.sort(key=lambda match: match.similarity, reverse=True)
        return scored[: self.top_k]

    def _conflict_reason(
        self,
        match: ExemplarMatch,
        classification: ClassificationResult,
        action: ProposedAction,
    ) -> str | None:
        if match.category != classification.category:
            return (
                f"exemplar consistency conflict: nearest exemplar "
                f"{match.exemplar_id!r} expects category {match.category!r}"
            )
        if match.requires_human and not action.risky:
            return (
                f"exemplar consistency conflict: nearest exemplar "
                f"{match.exemplar_id!r} expects human review"
            )
        return None

    def _load_exemplars(self, settings: Settings) -> tuple[TriageExemplar, ...]:
        path_value = settings.exemplar_guard_examples_path
        path = Path(path_value) if path_value else DEFAULT_EXEMPLAR_PATH
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return DEFAULT_EXEMPLARS

        try:
            return tuple(_load_jsonl(path))
        except Exception:
            LOGGER.warning(
                "failed loading exemplar guard examples",
                exc_info=True,
                extra={"event": "exemplar_guard_examples_load_failed", "context": {"path": str(path)}},
            )
            return DEFAULT_EXEMPLARS


def _load_jsonl(path: Path) -> list[TriageExemplar]:
    exemplars: list[TriageExemplar] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            category = str(payload["category"])
            if category not in VALID_CATEGORIES:
                raise ValueError(f"invalid exemplar category: {category}")
            exemplars.append(
                TriageExemplar(
                    exemplar_id=str(payload["id"]),
                    text=str(payload["text"]),
                    category=cast(Category, category),
                    requires_human=bool(payload["requires_human"]),
                )
            )
    return exemplars


def _similarity(left: str, right: str) -> float:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if not left_normalized or not right_normalized:
        return 0.0
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    token_jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence_ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    return max(token_jaccard, sequence_ratio)


def _normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))
