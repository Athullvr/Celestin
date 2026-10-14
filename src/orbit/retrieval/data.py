"""Database-neutral records and operations consumed by retrieval orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """Normalized hit returned by a keyword index."""

    record_id: str
    project: str
    content: str
    timestamp: str | None
    source_id: str | None
    score: float
    status: str | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    """Ordered hits and the backend's existing match tier."""

    matches: tuple[SearchMatch, ...]
    tier: str


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """Authoritative project-scoped message record."""

    message_id: str
    project: str
    conversation_id: str
    content: str
    created_at: str | None


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Authoritative project-scoped canonical decision record."""

    decision_id: str
    project: str
    value: str
    updated_at: str | None
    source_message_id: str | None
    status: str


class RetrievalData(Protocol):
    """The persistence/index reads required by the shared retrieval use cases."""

    def search_messages(
        self, project: str, query: str, limit: int, *, relax: bool
    ) -> SearchPage: ...

    def search_decisions(
        self, project: str, query: str, limit: int, *, relax: bool
    ) -> SearchPage: ...

    def load_messages(
        self, project: str, message_ids: Sequence[str]
    ) -> dict[str, MessageRecord]: ...

    def load_decisions(
        self, project: str, decision_ids: Sequence[str]
    ) -> dict[str, DecisionRecord]: ...
