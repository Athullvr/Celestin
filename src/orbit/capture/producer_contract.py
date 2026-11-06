"""Versioned internal contract for producer deliveries into Capture.

This contract is owned by Celestin. It does not assert compatibility with an
external producer or transport schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from orbit.evidence.canonicalization import canonical_json_bytes
from orbit.evidence.model import EvidenceSource, EvidenceType, ProducerConflictReference

from .model import CandidateCategory, CaptureEvent, CaptureInput, CaptureSourceType

PRODUCER_DELIVERY_SCHEMA_VERSION = 1
PRODUCER_DELIVERY_HASH_VERSION = "celestin-producer-delivery-v1+jcs-rfc8785+sha256"
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_DELIVERY_OCCURRENCES = 200


class ProducerDeliveryValidationError(ValueError):
    """A typed internal producer delivery is malformed or incomplete."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProducerDeliveryValidationError("invalid_field", f"{field} must be non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class ProducerEvidenceReference:
    """One evidence association in the same project-scoped source namespace."""

    evidence_type: EvidenceType
    source_id: str
    source_namespace: str
    locator: str | None = None
    revision: str | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_type, EvidenceType):
            raise ProducerDeliveryValidationError("invalid_field", "evidence_type must be EvidenceType")
        _text(self.source_id, "evidence.source_id")
        _text(self.source_namespace, "evidence.source_namespace")
        for field in ("locator", "revision"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or "\x00" in value):
                raise ProducerDeliveryValidationError("invalid_field", f"evidence.{field} must be text or None")
        if self.content_hash is not None and (
            not isinstance(self.content_hash, str) or _HASH_RE.fullmatch(self.content_hash) is None
        ):
            raise ProducerDeliveryValidationError(
                "invalid_field", "evidence.content_hash must be null or lowercase sha256 hex"
            )

    def to_evidence_source(self) -> EvidenceSource:
        return EvidenceSource(
            self.evidence_type,
            self.source_id,
            self.locator,
            self.revision,
            self.content_hash,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type.value,
            "source_id": self.source_id,
            "source_namespace": self.source_namespace,
            "locator": self.locator,
            "revision": self.revision,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ProducerOccurrence:
    """One ordered occurrence; repeated values remain separate list entries."""

    ordinal: int
    category: CandidateCategory
    claim: str
    evidence: tuple[ProducerEvidenceReference, ...]
    source_id: str | None = None
    source_revision: str | None = None
    occurred_at: str | None = None
    locator: str | None = None
    conflicts: tuple[ProducerConflictReference, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ProducerDeliveryValidationError("invalid_ordinal", "ordinal must be a non-negative integer")
        if not isinstance(self.category, CandidateCategory):
            raise ProducerDeliveryValidationError("invalid_field", "category must be CandidateCategory")
        _text(self.claim, "claim")
        evidence = tuple(self.evidence)
        if not evidence:
            raise ProducerDeliveryValidationError(
                "incomplete_evidence", f"occurrence {self.ordinal} has no evidence references"
            )
        if any(not isinstance(item, ProducerEvidenceReference) for item in evidence):
            raise ProducerDeliveryValidationError("invalid_field", "evidence must contain typed references")
        for field in ("source_id", "source_revision", "occurred_at", "locator"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip() or "\x00" in value):
                raise ProducerDeliveryValidationError("invalid_field", f"{field} must be non-empty text or None")
        if any(not isinstance(item, ProducerConflictReference) for item in self.conflicts):
            raise ProducerDeliveryValidationError("invalid_conflict", "conflicts must be typed candidate references")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "conflicts", tuple(self.conflicts))

    def as_dict(self, *, inherited_source_id: str, inherited_revision: str | None,
                inherited_timestamp: str | None) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "category": self.category.value,
            "claim": self.claim,
            "source_id": self.source_id or inherited_source_id,
            "source_revision": self.source_revision or inherited_revision,
            "occurred_at": self.occurred_at or inherited_timestamp,
            "locator": self.locator,
            "evidence": [item.as_dict() for item in self.evidence],
            "conflicts": [_conflict_dict(item) for item in self.conflicts],
        }


@dataclass(frozen=True, slots=True)
class ProducerDelivery:
    """One immutable delivery identity and its producer payload revision."""

    project_id: str
    producer_id: str
    source_namespace: str
    delivery_id: str
    payload_revision_id: str
    source_type: CaptureSourceType
    source_id: str
    occurrences: tuple[ProducerOccurrence, ...]
    source_revision: str | None = None
    occurred_at: str | None = None
    schema_version: int = PRODUCER_DELIVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != PRODUCER_DELIVERY_SCHEMA_VERSION:
            raise ProducerDeliveryValidationError("unsupported_schema", "unsupported producer delivery schema_version")
        for field in ("project_id", "producer_id", "source_namespace", "delivery_id",
                      "payload_revision_id", "source_id"):
            _text(getattr(self, field), field)
        if self.source_revision is not None:
            _text(self.source_revision, "source_revision")
        if self.occurred_at is not None:
            _text(self.occurred_at, "occurred_at")
            _validate_timestamp(self.occurred_at, "occurred_at")
        if not isinstance(self.source_type, CaptureSourceType):
            raise ProducerDeliveryValidationError("invalid_field", "source_type must be CaptureSourceType")
        occurrences = tuple(self.occurrences)
        if not occurrences or len(occurrences) > MAX_DELIVERY_OCCURRENCES:
            raise ProducerDeliveryValidationError(
                "invalid_occurrences", f"occurrences must contain 1-{MAX_DELIVERY_OCCURRENCES} items"
            )
        if any(not isinstance(item, ProducerOccurrence) for item in occurrences):
            raise ProducerDeliveryValidationError("invalid_occurrences", "occurrences must be typed values")
        if [item.ordinal for item in occurrences] != list(range(len(occurrences))):
            raise ProducerDeliveryValidationError(
                "invalid_ordinal", "occurrence ordinals must be ordered and contiguous from zero"
            )
        for occurrence in occurrences:
            if occurrence.occurred_at is not None:
                _validate_timestamp(occurrence.occurred_at, f"occurrences[{occurrence.ordinal}].occurred_at")
            if any(item.source_namespace != self.source_namespace for item in occurrence.evidence):
                raise ProducerDeliveryValidationError(
                    "source_namespace_mismatch", "evidence namespace must match the delivery source namespace"
                )
        object.__setattr__(self, "occurrences", occurrences)

    def payload_document(self) -> dict[str, object]:
        """Return the exact versioned equality projection; arrays preserve order."""
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "producer_id": self.producer_id,
            "source_namespace": self.source_namespace,
            "delivery_id": self.delivery_id,
            "payload_revision_id": self.payload_revision_id,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "occurred_at": self.occurred_at,
            "occurrences": [
                item.as_dict(
                    inherited_source_id=self.source_id,
                    inherited_revision=self.source_revision,
                    inherited_timestamp=self.occurred_at,
                )
                for item in self.occurrences
            ],
        }

    def canonical_payload(self) -> bytes:
        return canonical_json_bytes(self.payload_document())

    def payload_hash(self) -> str:
        return hashlib.sha256(self.canonical_payload()).hexdigest()

    def to_capture_input(self) -> CaptureInput:
        return CaptureInput(
            project_id=self.project_id,
            source_type=self.source_type,
            source_id=self.source_id,
            source_revision=self.source_revision,
            source_timestamp=self.occurred_at,
            content=tuple(
                CaptureEvent(
                    category=item.category,
                    claim=item.claim,
                    evidence=tuple(evidence.to_evidence_source() for evidence in item.evidence),
                    locator=item.locator,
                    source_timestamp=item.occurred_at,
                    source_revision=item.source_revision,
                )
                for item in self.occurrences
            ),
        )


def _conflict_dict(value: ProducerConflictReference) -> dict[str, object]:
    return {
        "producer_id": value.producer_id,
        "candidate_id": value.candidate_id,
        "candidate_revision": value.candidate_revision,
    }


def _validate_timestamp(value: str, field: str) -> None:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProducerDeliveryValidationError("invalid_timestamp", f"{field} must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ProducerDeliveryValidationError("invalid_timestamp", f"{field} must include a timezone")
