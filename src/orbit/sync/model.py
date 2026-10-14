"""Versioned, source-attributed events for the synchronization prototype."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from orbit.capture.model import CandidateCategory, CaptureSourceReference
from orbit.evidence.model import EvidenceSource


CURRENT_SCHEMA_VERSION = 1


class SyncEventType(str, Enum):
    PROJECT_UPDATE = "project_update"
    DECISION_RECORDED = "decision_recorded"
    TASK_COMPLETED = "task_completed"
    BLOCKER_IDENTIFIED = "blocker_identified"
    EXECUTION_SUMMARY_PUBLISHED = "execution_summary_published"


@dataclass(frozen=True, slots=True)
class SyncPayload:
    """Concise untrusted update text and an optional Capability 3 category."""

    summary: str
    category: CandidateCategory | None = None


@dataclass(frozen=True, slots=True)
class SyncEventSubmission:
    """Client-supplied event fields; project/client labels are not credentials."""

    schema_version: int
    project_id: str
    source_client_id: str
    idempotency_key: str
    event_type: SyncEventType
    payload: SyncPayload
    source_occurred_at: str | None = None
    source_references: tuple[CaptureSourceReference, ...] = ()
    evidence: tuple[EvidenceSource, ...] = ()
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class SyncEvent:
    """Canonical event after receipt; sequence follows ingestion order."""

    event_id: str
    schema_version: int
    project_id: str
    source_client_id: str
    idempotency_key: str
    event_type: SyncEventType
    payload: SyncPayload
    source_occurred_at: str | None
    ingested_at: str
    source_references: tuple[CaptureSourceReference, ...]
    evidence: tuple[EvidenceSource, ...]
    correlation_id: str | None
    sequence: int


@dataclass(frozen=True, slots=True)
class SyncReceipt:
    """Acknowledgement; duplicate means the canonical event already existed."""

    event: SyncEvent
    duplicate: bool


@dataclass(frozen=True, slots=True)
class SyncEventPage:
    """At-least-once delivery page and checkpoint for the next request."""

    events: tuple[SyncEvent, ...]
    next_cursor: str
    has_more: bool
