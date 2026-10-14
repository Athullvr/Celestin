"""Database-neutral records and persistence operations used by the app layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SourceMessageNotFoundError(LookupError):
    """A source message does not exist in the requested project."""


class ProjectNotFoundError(LookupError):
    """A project is not provisioned in the configured storage workspace."""


class DecisionNotFoundError(LookupError):
    """A decision does not exist in the requested project."""


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A persisted chat message without database-driver-specific fields."""

    message_id: str
    project: str
    conversation_id: str
    role: str
    content: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StoredDecision:
    """A persisted decision; IDs are opaque to callers of the storage port."""

    decision_id: str
    project: str
    key: str
    value: str
    status: str
    source_message_id: str | None
    created_at: str
    updated_at: str


class MemoryStore(Protocol):
    """Persistence operations currently required by Celestin application code.

    Implementations own source-reference validation and storage transactions.
    Authorization remains in the application/MCP boundary.
    """

    def insert_message(
        self, project: str, conversation_id: str, role: str, content: str
    ) -> StoredMessage: ...

    def save_decision(
        self,
        project: str,
        key: str,
        value: str,
        source_message_id: str,
        status: str = "draft",
    ) -> StoredDecision: ...

    def update_decision_status(
        self, project: str, key: str, status: str
    ) -> StoredDecision: ...
