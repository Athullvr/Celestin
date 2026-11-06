"""Immutable records for claims and the evidence associated with them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KnowledgeType(str, Enum):
    DECISION = "decision"
    DISCOVERY = "discovery"
    BUG_FIX = "bug_fix"
    IMPLEMENTATION_FINDING = "implementation_finding"
    COMPLETED_WORK = "completed_work"
    REQUIREMENT = "requirement"
    OPEN_QUESTION = "open_question"


class EvidenceType(str, Enum):
    MESSAGE = "message"
    REPOSITORY_FILE = "repository_file"
    GIT_COMMIT = "git_commit"
    TEST_RESULT = "test_result"
    DOCUMENT = "document"
    OTHER = "other"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    STALE = "stale"
    CONFLICTING = "conflicting"


class LifecycleStatus(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ReferenceStatus(str, Enum):
    AVAILABLE = "available"
    UNRESOLVED = "unresolved"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """A reference to an existing source; source contents are not copied."""

    evidence_type: EvidenceType
    source_id: str
    locator: str | None = None
    revision: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    project: str
    evidence_type: EvidenceType
    source_id: str
    locator: str | None
    revision: str | None
    content_hash: str | None
    captured_at: str
    reference_status: ReferenceStatus
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    checked_at: str | None = None
    checked_by: str | None = None
    check_note: str | None = None


@dataclass(frozen=True, slots=True)
class CaptureSourceProvenance:
    """Original capture-source locator and occurrence time, before evidence mapping."""

    source_type: str
    source_id: str
    occurred_at: str | None = None
    revision: str | None = None
    locator: str | None = None


@dataclass(frozen=True, slots=True)
class ProducerConflictReference:
    """An explicit reference to one producer-owned candidate revision."""

    producer_id: str
    candidate_id: str
    candidate_revision: int

    def __post_init__(self) -> None:
        for name in ("producer_id", "candidate_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be non-empty text without NUL")
        if (
            isinstance(self.candidate_revision, bool)
            or not isinstance(self.candidate_revision, int)
            or self.candidate_revision < 1
        ):
            raise ValueError("candidate_revision must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProducerOccurrenceProvenance:
    """One producer occurrence, retaining its ordinal and duplicate evidence."""

    ordinal: int
    category: str
    claim: str
    source_namespace: str
    source_id: str
    source_revision: str | None
    occurred_at: str | None
    locator: str | None
    evidence: tuple[EvidenceSource, ...]
    candidate_id: str
    candidate_revision: int

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        for name in (
            "category", "claim", "source_namespace", "source_id", "candidate_id"
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be non-empty text without NUL")
        for name in ("source_revision", "occurred_at", "locator"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or "\x00" in value):
                raise ValueError(f"{name} must be text or None")
        evidence = tuple(self.evidence)
        if not evidence or any(not isinstance(item, EvidenceSource) for item in evidence):
            raise ValueError("each producer occurrence must retain at least one EvidenceSource")
        if (
            isinstance(self.candidate_revision, bool)
            or not isinstance(self.candidate_revision, int)
            or self.candidate_revision < 1
        ):
            raise ValueError("candidate_revision must be a positive integer")
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class ProducerDeliveryProvenance:
    """Versioned internal producer provenance carried through Knowledge reads."""

    schema_version: int
    producer_id: str
    source_namespace: str
    delivery_id: str
    payload_revision_id: str
    payload_hash_version: str
    payload_hash: str
    occurrences: tuple[ProducerOccurrenceProvenance, ...]
    conflicts: tuple[ProducerConflictReference, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported producer provenance schema_version")
        for name in (
            "producer_id", "source_namespace", "delivery_id", "payload_revision_id",
            "payload_hash_version", "payload_hash",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be non-empty text without NUL")
        if len(self.payload_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.payload_hash
        ):
            raise ValueError("payload_hash must be lowercase SHA-256 hex")
        occurrences = tuple(self.occurrences)
        conflicts = tuple(self.conflicts)
        if not occurrences or any(not isinstance(item, ProducerOccurrenceProvenance) for item in occurrences):
            raise ValueError("producer provenance must include typed occurrences")
        if any(not isinstance(item, ProducerConflictReference) for item in conflicts):
            raise ValueError("conflicts must contain ProducerConflictReference values")
        object.__setattr__(self, "occurrences", occurrences)
        object.__setattr__(self, "conflicts", conflicts)


@dataclass(frozen=True, slots=True)
class CaptureKnowledgeProvenance:
    """Review and capture metadata carried with a converted knowledge claim.

    Reviewer labels are provenance supplied by the capture domain. They are not
    authenticated identities and do not establish verification.
    """

    candidate_id: str
    project_id: str
    category: str
    certainty: str
    review_status: str
    candidate_verification_status: str
    source_references: tuple[CaptureSourceProvenance, ...]
    candidate_created_at: str
    candidate_updated_at: str
    original_claim: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    conflicts_with: tuple[str, ...] = ()
    producer_delivery: ProducerDeliveryProvenance | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    knowledge_id: str
    project: str
    knowledge_type: KnowledgeType
    claim: str
    created_at: str
    updated_at: str
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    lifecycle_status: LifecycleStatus = LifecycleStatus.CURRENT
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    checked_at: str | None = None
    checked_by: str | None = None
    check_note: str | None = None
    capture_provenance: CaptureKnowledgeProvenance | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeBundle:
    record: KnowledgeRecord
    evidence: tuple[EvidenceRecord, ...]
