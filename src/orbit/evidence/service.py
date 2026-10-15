"""Authorized domain service for evidence-linked knowledge.

Persistence is supplied through a storage-neutral port. SQLite and PostgreSQL
adapters do not implement this port yet; see docs/evidence-linked-memory-contract.md.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from orbit.mcp_server.authorization import AuthorizedProject, READ, WRITE

from .model import (
    EvidenceRecord,
    EvidenceSource,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    LifecycleStatus,
    ReferenceStatus,
    VerificationStatus,
)


class EvidenceMemoryError(RuntimeError):
    """Base class for evidence-linked memory service failures."""


class EvidenceValidationError(EvidenceMemoryError, ValueError):
    """A caller supplied an invalid record or evidence reference."""


class EvidenceReferenceMissing(EvidenceMemoryError):
    """A source resolver confirmed that a referenced source does not exist."""


class EvidenceNotAssociated(EvidenceMemoryError):
    """An evidence ID is not associated with the requested knowledge record."""


class EvidenceReferenceResolutionError(EvidenceMemoryError):
    """A source resolver failed; the reference was not treated as verified."""


class KnowledgeNotFound(EvidenceMemoryError):
    """A knowledge record does not exist in the authorized project."""


class InvalidKnowledgeTransition(EvidenceMemoryError):
    """A lifecycle transition is invalid or would discard history."""


class EvidenceLinkedMemoryStore(Protocol):
    """Minimal persistence contract; adapters must enforce project-scoped IDs.

    ``create_knowledge`` and ``supersede_knowledge`` are atomic operations.
    ``attach_evidence`` is idempotent for the same project, knowledge record,
    evidence type, source ID, locator, revision, and content hash, returning the
    existing evidence row.
    """

    def create_knowledge(
        self, record: KnowledgeRecord, evidence: Sequence[EvidenceRecord]
    ) -> None: ...

    def attach_evidence(
        self, project: str, knowledge_id: str, evidence: EvidenceRecord
    ) -> EvidenceRecord: ...

    def get_knowledge(self, project: str, knowledge_id: str) -> KnowledgeRecord | None: ...

    def list_evidence(
        self, project: str, knowledge_id: str
    ) -> Sequence[EvidenceRecord]: ...

    def set_knowledge_verification(
        self, project: str, knowledge_id: str, record: KnowledgeRecord
    ) -> None: ...

    def set_evidence_verification(
        self, project: str, knowledge_id: str, evidence: EvidenceRecord
    ) -> None: ...

    def supersede_knowledge(
        self,
        project: str,
        previous_id: str,
        successor: KnowledgeRecord,
        evidence: Sequence[EvidenceRecord],
    ) -> None: ...


class EvidenceReferenceResolver(Protocol):
    """Resolve a source identifier inside a project, without inferring truth."""

    def resolve(self, project: str, source: EvidenceSource) -> ReferenceStatus: ...


class EvidenceLinkedMemoryService:
    """Create, associate, inspect, verify, and supersede project knowledge.

    Every operation requires an ``AuthorizedProject`` produced by Celestin's
    existing authorization boundary. Verification status changes are explicit
    caller assertions; this service never checks source truth on its own.
    """

    def __init__(
        self,
        store: EvidenceLinkedMemoryStore,
        resolver: EvidenceReferenceResolver,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_knowledge(
        self,
        scope: AuthorizedProject,
        knowledge_type: KnowledgeType,
        claim: str,
        evidence_sources: Sequence[EvidenceSource],
    ) -> KnowledgeBundle:
        project = _require_scope(scope, WRITE)
        claim = _required_text(claim, "claim")
        if not isinstance(knowledge_type, KnowledgeType):
            raise EvidenceValidationError("knowledge_type must be a KnowledgeType")
        if not evidence_sources:
            raise EvidenceValidationError("at least one evidence source is required")

        now = self._now()
        evidence = self._new_evidence(project, evidence_sources, now)
        record = KnowledgeRecord(
            knowledge_id=self._new_id(),
            project=project,
            knowledge_type=knowledge_type,
            claim=claim,
            created_at=now,
            updated_at=now,
        )
        self._store.create_knowledge(record, evidence)
        return KnowledgeBundle(record=record, evidence=evidence)

    def associate_evidence(
        self,
        scope: AuthorizedProject,
        knowledge_id: str,
        source: EvidenceSource,
    ) -> EvidenceRecord:
        project = _require_scope(scope, WRITE)
        knowledge_id = _required_text(knowledge_id, "knowledge_id")
        self._require_record(project, knowledge_id)
        evidence = self._new_evidence(project, (source,), self._now())[0]
        return self._store.attach_evidence(project, knowledge_id, evidence)

    def get_knowledge(
        self, scope: AuthorizedProject, knowledge_id: str
    ) -> KnowledgeBundle:
        project = _require_scope(scope, READ)
        knowledge_id = _required_text(knowledge_id, "knowledge_id")
        record = self._require_record(project, knowledge_id)
        evidence = tuple(self._store.list_evidence(project, knowledge_id))
        # Re-resolve references at read time. Availability is not proof that
        # evidence is current or that it supports the claim.
        refreshed = tuple(
            replace(
                item,
                reference_status=self._resolve(
                    project,
                    EvidenceSource(
                        item.evidence_type,
                        item.source_id,
                        item.locator,
                        item.revision,
                        item.content_hash,
                    ),
                ),
            )
            for item in evidence
        )
        return KnowledgeBundle(record=record, evidence=refreshed)

    def set_knowledge_verification(
        self,
        scope: AuthorizedProject,
        knowledge_id: str,
        status: VerificationStatus,
        *,
        checked_by: str | None = None,
        note: str | None = None,
    ) -> KnowledgeRecord:
        project = _require_scope(scope, WRITE)
        record = self._require_record(project, _required_text(knowledge_id, "knowledge_id"))
        checked_by, note = _verification_metadata(status, checked_by, note)
        now = self._now()
        checked_at = (
            record.checked_at
            if status is VerificationStatus.UNVERIFIED
            else now
        )
        if status is VerificationStatus.UNVERIFIED:
            checked_by, note = record.checked_by, record.check_note
        updated = replace(
            record,
            verification_status=status,
            updated_at=now,
            checked_at=checked_at,
            checked_by=checked_by,
            check_note=note,
        )
        self._store.set_knowledge_verification(project, knowledge_id, updated)
        return updated

    def set_evidence_verification(
        self,
        scope: AuthorizedProject,
        knowledge_id: str,
        evidence_id: str,
        status: VerificationStatus,
        *,
        checked_by: str | None = None,
        note: str | None = None,
    ) -> EvidenceRecord:
        project = _require_scope(scope, WRITE)
        knowledge_id = _required_text(knowledge_id, "knowledge_id")
        evidence_id = _required_text(evidence_id, "evidence_id")
        self._require_record(project, knowledge_id)
        evidence = self._store.list_evidence(project, knowledge_id)
        target = next((item for item in evidence if item.evidence_id == evidence_id), None)
        if target is None:
            raise EvidenceNotAssociated("evidence is not associated with this knowledge record")
        if target.project != project:
            raise EvidenceMemoryError("storage returned evidence outside the requested project")
        checked_by, note = _verification_metadata(status, checked_by, note)
        checked_at = (
            target.checked_at
            if status is VerificationStatus.UNVERIFIED
            else self._now()
        )
        if status is VerificationStatus.UNVERIFIED:
            checked_by, note = target.checked_by, target.check_note
        updated = replace(
            target,
            verification_status=status,
            checked_at=checked_at,
            checked_by=checked_by,
            check_note=note,
        )
        self._store.set_evidence_verification(project, knowledge_id, updated)
        return updated

    def supersede_knowledge(
        self,
        scope: AuthorizedProject,
        previous_id: str,
        knowledge_type: KnowledgeType,
        claim: str,
        evidence_sources: Sequence[EvidenceSource],
    ) -> KnowledgeBundle:
        project = _require_scope(scope, WRITE)
        previous_id = _required_text(previous_id, "previous_id")
        previous = self._require_record(project, previous_id)
        if previous.lifecycle_status is not LifecycleStatus.CURRENT:
            raise InvalidKnowledgeTransition("only a current record can be superseded")
        claim = _required_text(claim, "claim")
        if not isinstance(knowledge_type, KnowledgeType):
            raise EvidenceValidationError("knowledge_type must be a KnowledgeType")
        if not evidence_sources:
            raise EvidenceValidationError("at least one evidence source is required")

        now = self._now()
        evidence = self._new_evidence(project, evidence_sources, now)
        successor = KnowledgeRecord(
            knowledge_id=self._new_id(),
            project=project,
            knowledge_type=knowledge_type,
            claim=claim,
            created_at=now,
            updated_at=now,
            supersedes_id=previous_id,
        )
        self._store.supersede_knowledge(project, previous_id, successor, evidence)
        return KnowledgeBundle(record=successor, evidence=evidence)

    def _new_evidence(
        self,
        project: str,
        sources: Sequence[EvidenceSource],
        captured_at: str,
    ) -> tuple[EvidenceRecord, ...]:
        validated: list[EvidenceSource] = []
        seen: set[tuple[EvidenceType, str, str | None, str | None, str | None]] = set()
        for source in sources:
            if not isinstance(source, EvidenceSource):
                raise EvidenceValidationError("each evidence source must be an EvidenceSource")
            if not isinstance(source.evidence_type, EvidenceType):
                raise EvidenceValidationError("evidence_type must be an EvidenceType")
            source_id = _required_text(source.source_id, "source_id")
            locator = _optional_text(source.locator, "locator")
            revision = _optional_text(source.revision, "revision")
            content_hash = _optional_text(source.content_hash, "content_hash")
            key = (
                source.evidence_type,
                source_id,
                locator,
                revision,
                content_hash,
            )
            if key in seen:
                continue
            seen.add(key)
            validated.append(
                replace(
                    source,
                    source_id=source_id,
                    locator=locator,
                    revision=revision,
                    content_hash=content_hash,
                )
            )
        if not validated:
            raise EvidenceValidationError("at least one unique evidence source is required")

        records: list[EvidenceRecord] = []
        for source in validated:
            resolution = self._resolve(project, source)
            if resolution is ReferenceStatus.MISSING:
                raise EvidenceReferenceMissing(
                    f"{source.evidence_type.value} source {source.source_id!r} was not found in project {project!r}"
                )
            records.append(
                EvidenceRecord(
                    evidence_id=self._new_id(),
                    project=project,
                    evidence_type=source.evidence_type,
                    source_id=source.source_id,
                    locator=source.locator,
                    revision=source.revision,
                    content_hash=source.content_hash,
                    captured_at=captured_at,
                    reference_status=resolution,
                )
            )
        return tuple(records)

    def _resolve(self, project: str, source: EvidenceSource) -> ReferenceStatus:
        try:
            result = self._resolver.resolve(project, source)
        except Exception as exc:
            raise EvidenceReferenceResolutionError(
                f"could not resolve {source.evidence_type.value} source {source.source_id!r}"
            ) from exc
        if not isinstance(result, ReferenceStatus):
            raise EvidenceReferenceResolutionError("resolver returned an invalid reference status")
        return result

    def _require_record(self, project: str, knowledge_id: str) -> KnowledgeRecord:
        record = self._store.get_knowledge(project, knowledge_id)
        if record is None:
            raise KnowledgeNotFound(
                f"knowledge record {knowledge_id!r} was not found in project {project!r}"
            )
        if record.project != project:
            raise EvidenceMemoryError("storage returned a record outside the requested project")
        return record

    def _new_id(self) -> str:
        value = self._id_factory()
        return _required_text(value, "generated identifier")

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise EvidenceValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )


def _require_scope(scope: AuthorizedProject, action: str) -> str:
    if not isinstance(scope, AuthorizedProject) or scope.action != action:
        raise PermissionError(f"an authorized project {action} scope is required")
    return _required_text(scope.project, "authorized project")


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise EvidenceValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _verification_metadata(
    status: VerificationStatus,
    checked_by: str | None,
    note: str | None,
) -> tuple[str | None, str | None]:
    if not isinstance(status, VerificationStatus):
        raise EvidenceValidationError("status must be a VerificationStatus")
    if status is VerificationStatus.UNVERIFIED:
        if checked_by is not None or note is not None:
            raise EvidenceValidationError("unverified status cannot include check metadata")
        return None, None
    if checked_by is None:
        raise EvidenceValidationError("checked_by is required when setting a checked status")
    checked_by = _required_text(checked_by, "checked_by")
    if note is not None and not isinstance(note, str):
        raise EvidenceValidationError("note must be a string or None")
    return checked_by, note.strip() if note else None
