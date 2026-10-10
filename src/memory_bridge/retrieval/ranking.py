"""Deterministic policy ranking for already retrieved records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .fts import SearchResult


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """A retrieval-layer record independent of database schema."""

    record_id: str
    project_id: str
    source_id: str
    content: str
    timestamp: str
    relevance_score: float
    record_kind: str
    status: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("record_id", "project_id", "source_id", "content", "timestamp"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
        if not self.record_id or not self.project_id or not self.source_id:
            raise ValueError("record_id, project_id, and source_id must be non-empty")
        if self.record_kind not in {"chat_message", "canonical_decision"}:
            raise ValueError("record_kind must be chat_message or canonical_decision")
        if self.record_kind == "chat_message" and self.status is not None:
            raise ValueError("chat_message status must be None")
        if self.record_kind == "canonical_decision" and self.status not in {
            "approved",
            "draft",
            "deprecated",
        }:
            raise ValueError("canonical_decision status must be approved, draft, or deprecated")
        if isinstance(self.relevance_score, bool) or not isinstance(self.relevance_score, (int, float)):
            raise TypeError("relevance_score must be a number")
        if not math.isfinite(self.relevance_score):
            raise ValueError("relevance_score must be finite")
        _timestamp_key(self.timestamp)

    @classmethod
    def from_message_search_result(cls, result: SearchResult) -> RetrievalCandidate:
        """Map the FTS baseline DTO into the cross-source ranking DTO."""
        if not isinstance(result, SearchResult):
            raise TypeError("result must be a SearchResult")
        return cls(
            record_id=result.message_id,
            project_id=result.project_id,
            source_id=result.source_id,
            content=result.content,
            timestamp=result.timestamp,
            relevance_score=result.relevance_score,
            record_kind="chat_message",
        )


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    """Explicit policy; recency breaks relevance ties without score weights."""

    include_drafts: bool = False
    include_deprecated: bool = False
    approved_decisions_first: bool = True
    recency_tiebreaker: bool = True


def _timestamp_key(timestamp: str) -> float:
    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"timestamp must be an ISO 8601 datetime: {timestamp!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def rank_candidates(
    candidates: Iterable[RetrievalCandidate],
    *,
    project_id: str,
    policy: RankingPolicy = RankingPolicy(),
) -> list[RetrievalCandidate]:
    """Filter and rank candidates under an explicit project and status policy.

    Ordering is lexicographic: approved canonical decision priority (when
    enabled), FTS relevance, optional recency tie-break, then stable record and
    source IDs. Scores remain untouched and represent keyword relevance only.
    """
    if not isinstance(project_id, str):
        raise TypeError("project_id must be a string")
    if not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if not isinstance(policy, RankingPolicy):
        raise TypeError("policy must be a RankingPolicy")

    eligible = []
    for candidate in candidates:
        if not isinstance(candidate, RetrievalCandidate):
            raise TypeError("candidates must contain RetrievalCandidate values")
        if candidate.project_id != project_id:
            continue
        if candidate.record_kind == "canonical_decision":
            if candidate.status == "deprecated" and not policy.include_deprecated:
                continue
            if candidate.status == "draft" and not policy.include_drafts:
                continue
        eligible.append(candidate)

    def ordering(candidate: RetrievalCandidate) -> tuple[object, ...]:
        if candidate.record_kind == "canonical_decision":
            if candidate.status == "approved":
                category = 0 if policy.approved_decisions_first else 1
            elif candidate.status == "draft":
                category = 2
            else:
                category = 3
        else:
            category = 1 if policy.approved_decisions_first else 0
        recency = -_timestamp_key(candidate.timestamp) if policy.recency_tiebreaker else 0
        return (
            category,
            candidate.relevance_score,
            recency,
            candidate.record_id,
            candidate.source_id,
        )

    return sorted(eligible, key=ordering)
