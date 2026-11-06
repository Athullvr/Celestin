"""Durable, request-scoped producer delivery and Capture conversion workflow.

The adapter owns no connection lifecycle. All writes share the authorized
request transaction, while per-operation savepoints make failures replayable.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Iterator, Protocol, Sequence
from uuid import uuid4

from orbit.evidence.canonicalization import CONVERSION_HASH_VERSION_V1, conversion_input_hash
from orbit.evidence.model import (
    EvidenceRecord,
    EvidenceSource,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    LifecycleStatus,
    ProducerConflictReference,
    ProducerDeliveryProvenance,
    ProducerOccurrenceProvenance,
    ReferenceStatus,
    VerificationStatus,
)
from orbit.evidence.postgres import PostgresEvidenceLinkedMemoryStore
from orbit.evidence.provenance_json import producer_delivery_from_dict, producer_delivery_to_dict
from orbit.mcp_server.hosted_scope import HostedAccessDenied, ResolvedProjectScope
from orbit.project_state.knowledge_read import (
    KnowledgeCoverage,
    KnowledgeReadFailure,
    KnowledgeReadFailureKind,
    KnowledgeReadResult,
)
from orbit.retrieval.knowledge import KnowledgeRetrievalResult, KnowledgeRetrievalService

from .model import (
    CandidateCertainty,
    CandidateCategory,
    CaptureResult,
    CaptureSourceReference,
    CaptureSourceType,
    KnowledgeCandidate,
    ReviewStatus,
)
from .producer_contract import (
    PRODUCER_DELIVERY_HASH_VERSION,
    ProducerDelivery,
    ProducerDeliveryValidationError,
    ProducerOccurrence,
)
from .service import (
    KnowledgeCapturePipeline,
    SensitiveContentRejected,
    capture_provenance_for,
    evidence_sources_for,
    knowledge_type_for_candidate,
)


class ProducerWorkflowError(RuntimeError):
    """A typed producer-delivery or conversion failure safe for application use."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProducerDeliveryOutcome(str, Enum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"


class ProducerReviewState(str, Enum):
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ProducerConversionOutcome(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"


class _Connection(Protocol):
    def execute(self, query: str, params: Sequence[object] = ()) -> Any: ...

    def transaction(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class DeliveryCandidateRevision:
    candidate_id: str
    candidate_revision: int
    first_occurrence_ordinal: int


@dataclass(frozen=True, slots=True)
class ProducerDeliveryReceipt:
    project_id: str
    producer_id: str
    source_namespace: str
    delivery_id: str
    payload_revision_id: str
    payload_hash: str
    received_at: str
    candidates: tuple[DeliveryCandidateRevision, ...]
    outcome: ProducerDeliveryOutcome = ProducerDeliveryOutcome.ACCEPTED

    @property
    def replayed(self) -> bool:
        return self.outcome is ProducerDeliveryOutcome.REPLAYED


@dataclass(frozen=True, slots=True)
class CandidateReviewResult:
    project_id: str
    candidate_id: str
    candidate_revision: int
    status: ProducerReviewState
    reviewer_id: str
    reviewed_at: str
    review_note: str | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CaptureCandidateRevisionView:
    project_id: str
    producer_id: str
    candidate_revision: int
    candidate: KnowledgeCandidate
    review_state: ProducerReviewState
    reviewer_id: str | None
    reviewed_at: str | None
    review_note: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeConversionResult:
    project_id: str
    producer_id: str
    candidate_id: str
    candidate_revision: int
    knowledge_id: str
    conversion_hash: str
    converted_at: str
    outcome: ProducerConversionOutcome = ProducerConversionOutcome.CREATED

    @property
    def replayed(self) -> bool:
        return self.outcome is ProducerConversionOutcome.REPLAYED


class PostgresProducerKnowledgeWorkflow:
    """Capture, review, convert, and read within one resolved project scope."""

    def __init__(
        self,
        connection: _Connection,
        scope: ResolvedProjectScope,
        evidence_store: PostgresEvidenceLinkedMemoryStore,
    ) -> None:
        if connection is None or not callable(getattr(connection, "execute", None)):
            raise TypeError("connection must provide execute()")
        if not callable(getattr(connection, "transaction", None)):
            raise TypeError("connection must provide transaction()")
        if not isinstance(scope, ResolvedProjectScope):
            raise TypeError("scope must be issued by HostedScopeResolver")
        self._connection = connection
        self._scope = scope
        self._evidence_store = evidence_store

    @classmethod
    def _for_request(
        cls,
        connection: _Connection,
        scope: ResolvedProjectScope,
        evidence_store: PostgresEvidenceLinkedMemoryStore,
    ) -> PostgresProducerKnowledgeWorkflow:
        return cls(connection, scope, evidence_store)

    def deliver(self, delivery: ProducerDelivery) -> ProducerDeliveryReceipt:
        """Persist one validated delivery; identical retries return its receipt."""
        if not isinstance(delivery, ProducerDelivery):
            raise ProducerWorkflowError("invalid_delivery", "delivery must be a ProducerDelivery")
        self._require_project(delivery.project_id)
        self._require_permission("write")
        try:
            capture = self._capture(delivery)
        except SensitiveContentRejected as exc:
            raise ProducerWorkflowError(
                "sensitive_content_rejected",
                "delivery contains sensitive content and was not persisted",
            ) from exc
        except ProducerDeliveryValidationError as exc:
            raise ProducerWorkflowError(exc.code, str(exc)) from exc
        except Exception as exc:
            raise ProducerWorkflowError(
                "capture_validation_failed", "producer delivery failed Capture validation"
            ) from exc

        result, occurrence_candidate_ids = capture
        if len(result.occurrences) != len(delivery.occurrences):
            raise ProducerWorkflowError(
                "incomplete_capture",
                "Capture did not preserve every producer occurrence; delivery was not persisted",
            )
        try:
            payload_hash = delivery.payload_hash()
        except Exception as exc:
            raise ProducerWorkflowError(
                "payload_canonicalization_failed", "delivery payload could not be canonicalized"
            ) from exc
        identity = (
            delivery.producer_id,
            delivery.source_namespace,
            delivery.delivery_id,
        )

        try:
            with self._atomic():
                self._lock_delivery_identity(identity)
                existing = self._load_receipt(identity)
                if existing is not None:
                    if existing.payload_hash != payload_hash:
                        raise ProducerWorkflowError(
                            "delivery_id_payload_conflict",
                            "delivery_id is already bound to a different payload revision or payload",
                        )
                    return replace(existing, outcome=ProducerDeliveryOutcome.REPLAYED)

                self._require_registered_source(delivery)
                revisions = self._reserve_candidate_revisions(result, delivery)
                self._validate_conflicts(delivery, occurrence_candidate_ids, revisions)
                candidate_refs = self._receipt_candidates(occurrence_candidate_ids, revisions)
                safe_payload = {
                    "schema_version": delivery.schema_version,
                    "project_id": delivery.project_id,
                    "producer_id": delivery.producer_id,
                    "source_namespace": delivery.source_namespace,
                    "delivery_id": delivery.delivery_id,
                    "payload_revision_id": delivery.payload_revision_id,
                    "occurrence_count": len(delivery.occurrences),
                    "occurrence_categories": [item.category.value for item in delivery.occurrences],
                    "payload_hash_version": PRODUCER_DELIVERY_HASH_VERSION,
                    "payload_hash": payload_hash,
                }
                receipt_row = self._fetchone(
                    """
                    INSERT INTO celestin_producer_delivery_receipts
                        (workspace_id, project_id, producer_id, source_namespace,
                         delivery_id, schema_version, payload_revision_id,
                         payload_hash_version, payload_hash, payload_json, receipt_outcome,
                         received_by_kind, received_by_issuer, received_by_subject,
                         received_by_user_id, received_by_service_identity_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
                    RETURNING received_at
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        delivery.producer_id,
                        delivery.source_namespace,
                        delivery.delivery_id,
                        delivery.schema_version,
                        delivery.payload_revision_id,
                        PRODUCER_DELIVERY_HASH_VERSION,
                        payload_hash,
                        _json(safe_payload),
                        _json({"status": "accepted", "candidates": [
                            _candidate_ref_dict(item) for item in candidate_refs
                        ]}),
                        self._scope.principal.kind,
                        self._scope.principal.issuer,
                        self._scope.principal.subject,
                        self._scope.principal_id if self._scope.principal.kind == "human" else None,
                        self._scope.principal_id if self._scope.principal.kind == "service" else None,
                    ),
                )
                if receipt_row is None:
                    raise ProducerWorkflowError("receipt_write_failed", "delivery receipt was not returned")

                first_ordinals = _first_occurrence_ordinals(occurrence_candidate_ids)
                for candidate in result.candidates:
                    candidate_revision = revisions[candidate.candidate_id]
                    candidate_occurrences = tuple(
                        (ordinal, delivery.occurrences[ordinal])
                        for ordinal, candidate_id in enumerate(occurrence_candidate_ids)
                        if candidate_id == candidate.candidate_id
                    )
                    provenance = self._delivery_provenance(
                        delivery,
                        payload_hash,
                        candidate.candidate_id,
                        candidate_revision,
                        candidate_occurrences,
                    )
                    typed_conflicts = tuple(
                        conflict
                        for occurrence in provenance.occurrences
                        for conflict in occurrence.conflicts
                    )
                    self._insert_candidate_revision(
                        delivery,
                        candidate,
                        candidate_revision,
                        provenance,
                        typed_conflicts,
                    )
                    self._insert_delivery_candidate_revision(
                        delivery,
                        candidate.candidate_id,
                        candidate_revision,
                        first_ordinals[candidate.candidate_id],
                    )
                    self._insert_candidate_evidence_and_occurrences(
                        delivery,
                        candidate,
                        candidate_revision,
                        candidate_occurrences,
                    )

                received_at = _utc_iso(receipt_row[0])
                return ProducerDeliveryReceipt(
                    project_id=delivery.project_id,
                    producer_id=delivery.producer_id,
                    source_namespace=delivery.source_namespace,
                    delivery_id=delivery.delivery_id,
                    payload_revision_id=delivery.payload_revision_id,
                    payload_hash=payload_hash,
                    received_at=received_at,
                    candidates=candidate_refs,
                )
        except ProducerWorkflowError:
            raise
        except Exception as exc:
            raise ProducerWorkflowError(
                "delivery_persistence_failed",
                "delivery was rolled back and can be retried with the same identity",
            ) from exc

    def approve(
        self,
        producer_id: str,
        candidate_id: str,
        candidate_revision: int,
        *,
        note: str | None = None,
    ) -> CandidateReviewResult:
        return self._review(producer_id, candidate_id, candidate_revision, ReviewStatus.APPROVED, note)

    def reject(
        self,
        producer_id: str,
        candidate_id: str,
        candidate_revision: int,
        *,
        note: str | None = None,
    ) -> CandidateReviewResult:
        return self._review(producer_id, candidate_id, candidate_revision, ReviewStatus.REJECTED, note)

    def get_candidate_revision(
        self, producer_id: str, candidate_id: str, candidate_revision: int
    ) -> CaptureCandidateRevisionView:
        """Read one immutable candidate revision and its latest review state."""
        self._require_permission("memory:read")
        producer_id = _required_text(producer_id, "producer_id")
        candidate_id = _required_text(candidate_id, "candidate_id")
        candidate_revision = _positive_int(candidate_revision, "candidate_revision")
        try:
            with self._atomic():
                revision, state = self._load_candidate_revision(
                    producer_id, candidate_id, candidate_revision
                )
                review = self._load_latest_review(producer_id, candidate_id, candidate_revision)
                return CaptureCandidateRevisionView(
                    project_id=self._scope.project_key,
                    producer_id=producer_id,
                    candidate_revision=candidate_revision,
                    candidate=_candidate_from_state(state),
                    review_state=(
                        ProducerReviewState.PENDING if review is None else ProducerReviewState(str(review[0]))
                    ),
                    reviewer_id=None if review is None else f"{review[3]}:{review[4]}",
                    reviewed_at=None if review is None else _utc_iso(review[1]),
                    review_note=None if review is None else review[2],
                )
        except ProducerWorkflowError:
            raise
        except Exception as exc:
            raise ProducerWorkflowError(
                "candidate_read_failed", "candidate revision could not be read"
            ) from exc

    def convert(
        self, producer_id: str, candidate_id: str, candidate_revision: int
    ) -> KnowledgeConversionResult:
        """Convert only the exact approved immutable candidate revision."""
        self._require_permission("write")
        self._require_permission("memory:convert")
        producer_id = _required_text(producer_id, "producer_id")
        candidate_id = _required_text(candidate_id, "candidate_id")
        candidate_revision = _positive_int(candidate_revision, "candidate_revision")
        try:
            with self._atomic():
                revision, state = self._load_candidate_revision(
                    producer_id, candidate_id, candidate_revision
                )
                review = self._load_latest_review(producer_id, candidate_id, candidate_revision)
                if review is None or review[0] != "approved":
                    raise ProducerWorkflowError(
                        "candidate_not_approved", "the exact candidate revision is not approved"
                    )
                if revision[5] != VerificationStatus.UNVERIFIED.value:
                    raise ProducerWorkflowError(
                        "candidate_not_convertible", "candidate verification status is not unverified"
                    )
                candidate = _candidate_from_state(state)
                reviewer_id = f"{review[3]}:{review[4]}"
                approved_at = _utc_iso(review[1])
                candidate = replace(
                    candidate,
                    status=ReviewStatus.APPROVED,
                    reviewed_by=reviewer_id,
                    reviewed_at=approved_at,
                    review_note=review[2],
                    updated_at=approved_at,
                )
                try:
                    knowledge_type = knowledge_type_for_candidate(candidate)
                    evidence_sources = evidence_sources_for(
                        candidate, target_project=self._scope.project_key
                    )
                    base_provenance = capture_provenance_for(
                        candidate, target_project=self._scope.project_key
                    )
                except Exception as exc:
                    raise ProducerWorkflowError(
                        "candidate_not_convertible",
                        "candidate category or review data has no agreed Knowledge conversion",
                    ) from exc

                producer_provenance = producer_delivery_from_dict(
                    state.get("producer_delivery")
                )
                if producer_provenance is None or producer_provenance.producer_id != producer_id:
                    raise ProducerWorkflowError(
                        "producer_provenance_missing", "candidate revision has no producer provenance"
                    )
                provenance = replace(
                    base_provenance,
                    producer_delivery=producer_provenance,
                    conflicts_with=tuple(
                        _conflict_label(item) for item in producer_provenance.conflicts
                    ),
                )
                conversion_payload = self._conversion_payload(
                    candidate_revision,
                    candidate,
                    producer_provenance,
                    knowledge_type.value,
                    reviewer_id,
                    approved_at,
                )
                conversion_hash = conversion_input_hash(conversion_payload)
                ledger = self._fetchone(
                    """
                    SELECT knowledge_id, payload_hash_version, payload_hash, converted_at
                      FROM celestin_candidate_conversions
                     WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
                       AND candidate_id = %s AND candidate_revision = %s
                     FOR UPDATE
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        producer_id,
                        candidate_id,
                        candidate_revision,
                    ),
                )
                if ledger is not None:
                    if ledger[1] != conversion_hash.hash_version or ledger[2] != conversion_hash.digest:
                        raise ProducerWorkflowError(
                            "conversion_payload_conflict",
                            "conversion ledger does not match the immutable approved revision",
                        )
                    record = self._evidence_store.get_knowledge(
                        self._scope.project_key, str(ledger[0])
                    )
                    if record is None:
                        raise ProducerWorkflowError(
                            "conversion_integrity_error", "conversion ledger points to missing Knowledge"
                        )
                    return KnowledgeConversionResult(
                        self._scope.project_key,
                        producer_provenance.producer_id,
                        candidate_id,
                        candidate_revision,
                        str(ledger[0]),
                        conversion_hash.digest,
                        _utc_iso(ledger[3]),
                        outcome=ProducerConversionOutcome.REPLAYED,
                    )

                knowledge_id = self._knowledge_id(
                    producer_id,
                    candidate_id,
                    candidate_revision,
                    conversion_hash.digest,
                )
                now = datetime.now(timezone.utc)
                now_iso = _utc_iso(now)
                record = KnowledgeRecord(
                    knowledge_id=knowledge_id,
                    project=self._scope.project_key,
                    knowledge_type=knowledge_type,
                    claim=candidate.claim,
                    created_at=now_iso,
                    updated_at=now_iso,
                    verification_status=VerificationStatus.UNVERIFIED,
                    lifecycle_status=LifecycleStatus.CURRENT,
                    capture_provenance=provenance,
                )
                evidence = tuple(
                    EvidenceRecord(
                        evidence_id=str(uuid4()),
                        project=self._scope.project_key,
                        evidence_type=source.evidence_type,
                        source_id=source.source_id,
                        locator=source.locator,
                        revision=source.revision,
                        content_hash=source.content_hash,
                        captured_at=now_iso,
                        reference_status=ReferenceStatus.UNRESOLVED,
                        verification_status=VerificationStatus.UNVERIFIED,
                    )
                    for source in evidence_sources
                )
                self._evidence_store.create_knowledge(record, evidence)
                conversion_time = self._fetchone(
                    """
                    INSERT INTO celestin_candidate_conversions
                        (workspace_id, project_id, producer_id, candidate_id,
                         candidate_revision, knowledge_id, payload_hash_version,
                         payload_hash, converted_by_kind, converted_by_issuer,
                         converted_by_subject)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING converted_at
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        producer_id,
                        candidate_id,
                        candidate_revision,
                        knowledge_id,
                        conversion_hash.hash_version,
                        conversion_hash.digest,
                        self._scope.principal.kind,
                        self._scope.principal.issuer,
                        self._scope.principal.subject,
                    ),
                )
                if conversion_time is None:
                    raise ProducerWorkflowError(
                        "conversion_write_failed", "conversion ledger entry was not returned"
                    )
                return KnowledgeConversionResult(
                    self._scope.project_key,
                    producer_id,
                    candidate_id,
                    candidate_revision,
                    knowledge_id,
                    conversion_hash.digest,
                    _utc_iso(conversion_time[0]),
                )
        except ProducerWorkflowError:
            raise
        except Exception as exc:
            raise ProducerWorkflowError(
                "conversion_failed",
                "conversion transaction was rolled back and can be retried",
            ) from exc

    def read_knowledge(self) -> KnowledgeReadResult:
        """Read typed Evidence-linked Knowledge without folding it into Retrieval."""
        project = self._scope.project_key
        if not self._scope.permissions.intersection({"read", "memory:read"}):
            return KnowledgeReadResult.scope_mismatch(project)
        try:
            records: Sequence[KnowledgeBundle] = self._evidence_store.list_knowledge_bundles(project)
            return KnowledgeReadResult.succeeded(
                project, records, coverage=KnowledgeCoverage.REPORTED_COMPLETE
            )
        except HostedAccessDenied:
            return KnowledgeReadResult.scope_mismatch(project)
        except Exception:
            return KnowledgeReadResult.failed(
                project,
                KnowledgeReadFailure(
                    KnowledgeReadFailureKind.UNAVAILABLE,
                    "project Knowledge read could not be completed",
                ),
            )

    def retrieve_knowledge(
        self,
        read_result: KnowledgeReadResult,
        query: str,
        *,
        limit: int = 20,
        token_budget: int = 2_000,
        relax: bool = True,
    ) -> KnowledgeRetrievalResult:
        """Run FTS over the scoped Knowledge index and bind hits to the typed read."""
        from orbit.retrieval.postgres_data import PostgresRetrievalData

        retrieval = PostgresRetrievalData._for_request(self._connection, self._scope)
        return KnowledgeRetrievalService(retrieval).retrieve(
            read_result,
            query,
            limit=limit,
            token_budget=token_budget,
            relax=relax,
        )

    def _capture(
        self, delivery: ProducerDelivery
    ) -> tuple[CaptureResult, tuple[str, ...]]:
        identity_namespace = "producer-" + hashlib.sha256(
            json.dumps(
                [delivery.producer_id, delivery.source_namespace],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        pipeline = KnowledgeCapturePipeline(
            delivery.project_id, identity_namespace=identity_namespace
        )
        result = pipeline.capture(delivery.to_capture_input())
        if result.suppressed:
            raise SensitiveContentRejected("one or more producer occurrences were suppressed")
        by_ordinal = {item.ordinal: item.candidate_id for item in result.occurrences}
        if tuple(sorted(by_ordinal)) != tuple(range(len(delivery.occurrences))):
            raise ProducerWorkflowError(
                "incomplete_capture", "Capture did not return every ordered producer occurrence"
            )
        return result, tuple(by_ordinal[index] for index in range(len(delivery.occurrences)))

    def _require_project(self, project_id: str) -> None:
        if project_id != self._scope.project_key:
            raise ProducerWorkflowError(
                "project_scope_mismatch", "producer delivery project does not match trusted project scope"
            )

    def _require_permission(self, permission: str) -> None:
        if permission not in self._scope.permissions:
            raise HostedAccessDenied("access denied")

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with self._connection.transaction():
            yield

    def _execute(self, query: str, params: Sequence[object] = ()) -> None:
        cursor = self._connection.execute(query, params)
        _close_cursor(cursor)

    def _fetchone(self, query: str, params: Sequence[object] = ()) -> Any:
        cursor = self._connection.execute(query, params)
        try:
            return cursor.fetchone()
        finally:
            _close_cursor(cursor)

    def _fetchall(self, query: str, params: Sequence[object] = ()) -> list[Any]:
        cursor = self._connection.execute(query, params)
        try:
            return list(cursor.fetchall())
        finally:
            _close_cursor(cursor)

    def _lock_delivery_identity(self, identity: tuple[str, str, str]) -> None:
        key = json.dumps(
            [
                str(self._scope.workspace_id),
                str(self._scope.project_id),
                *identity,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fetchone(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s, 0))",
            (key,),
        )

    def _load_receipt(
        self, identity: tuple[str, str, str]
    ) -> ProducerDeliveryReceipt | None:
        row = self._fetchone(
            """
            SELECT payload_revision_id, payload_hash_version, payload_hash,
                   receipt_outcome, received_at
              FROM celestin_producer_delivery_receipts
             WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
               AND source_namespace = %s AND delivery_id = %s
             FOR UPDATE
            """,
            (self._scope.workspace_id, self._scope.project_id, *identity),
        )
        if row is None:
            return None
        payload_revision_id, hash_version, payload_hash, outcome, received_at = row
        if hash_version != PRODUCER_DELIVERY_HASH_VERSION:
            raise ProducerWorkflowError(
                "receipt_integrity_error", "stored receipt uses an unsupported delivery hash version"
            )
        outcome_value = _json_value(outcome)
        try:
            candidate_refs = tuple(
                DeliveryCandidateRevision(
                    candidate_id=_required_text(item["candidate_id"], "candidate_id"),
                    candidate_revision=_positive_int(item["candidate_revision"], "candidate_revision"),
                    first_occurrence_ordinal=_nonnegative_int(
                        item["first_occurrence_ordinal"], "first_occurrence_ordinal"
                    ),
                )
                for item in outcome_value["candidates"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProducerWorkflowError(
                "receipt_integrity_error", "stored delivery receipt outcome is invalid"
            ) from exc
        producer_id, source_namespace, delivery_id = identity
        return ProducerDeliveryReceipt(
            project_id=self._scope.project_key,
            producer_id=producer_id,
            source_namespace=source_namespace,
            delivery_id=delivery_id,
            payload_revision_id=str(payload_revision_id),
            payload_hash=str(payload_hash),
            received_at=_utc_iso(received_at),
            candidates=candidate_refs,
        )

    def _require_registered_source(self, delivery: ProducerDelivery) -> None:
        producer = self._fetchone(
            """
            SELECT 1 FROM celestin_project_producers
             WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
            """,
            (self._scope.workspace_id, self._scope.project_id, delivery.producer_id),
        )
        if producer is None:
            raise ProducerWorkflowError(
                "producer_not_registered", "producer is not registered for this project"
            )
        namespace = self._fetchone(
            """
            SELECT 1 FROM celestin_project_source_namespaces
             WHERE workspace_id = %s AND project_id = %s AND source_namespace = %s
            """,
            (self._scope.workspace_id, self._scope.project_id, delivery.source_namespace),
        )
        if namespace is None:
            raise ProducerWorkflowError(
                "source_namespace_not_registered", "source namespace is not registered for this project"
            )

    def _validate_conflicts(
        self,
        delivery: ProducerDelivery,
        candidate_ids: Sequence[str],
        revisions: dict[str, int],
    ) -> None:
        same_delivery = {
            (delivery.producer_id, candidate_id, revision)
            for candidate_id, revision in revisions.items()
        }
        for ordinal, (occurrence, candidate_id) in enumerate(zip(delivery.occurrences, candidate_ids)):
            candidate_identity = (
                delivery.producer_id,
                candidate_id,
                revisions[candidate_id],
            )
            for conflict in occurrence.conflicts:
                identity = (
                    conflict.producer_id,
                    conflict.candidate_id,
                    conflict.candidate_revision,
                )
                if identity == candidate_identity:
                    raise ProducerWorkflowError(
                        "self_conflict", f"occurrence {ordinal} cannot conflict with its own revision"
                    )
                if identity in same_delivery:
                    continue
                row = self._fetchone(
                    """
                    SELECT 1 FROM celestin_candidate_revisions
                     WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
                       AND candidate_id = %s AND candidate_revision = %s
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        conflict.producer_id,
                        conflict.candidate_id,
                        conflict.candidate_revision,
                    ),
                )
                if row is None:
                    raise ProducerWorkflowError(
                        "conflict_reference_unresolved",
                        f"occurrence {ordinal} references a candidate revision outside this project",
                    )

    def _reserve_candidate_revisions(
        self, result: CaptureResult, delivery: ProducerDelivery
    ) -> dict[str, int]:
        revisions: dict[str, int] = {}
        for candidate_id in sorted(candidate.candidate_id for candidate in result.candidates):
            self._execute(
                """
                INSERT INTO celestin_candidates
                    (workspace_id, project_id, producer_id, candidate_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (workspace_id, project_id, producer_id, candidate_id) DO NOTHING
                """,
                (
                    self._scope.workspace_id,
                    self._scope.project_id,
                    delivery.producer_id,
                    candidate_id,
                ),
            )
            locked = self._fetchone(
                """
                SELECT candidate_id FROM celestin_candidates
                 WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
                   AND candidate_id = %s
                 FOR UPDATE
                """,
                (
                    self._scope.workspace_id,
                    self._scope.project_id,
                    delivery.producer_id,
                    candidate_id,
                ),
            )
            if locked is None:
                raise ProducerWorkflowError(
                    "candidate_identity_missing", "Capture candidate identity could not be locked"
                )
            row = self._fetchone(
                """
                SELECT COALESCE(MAX(candidate_revision), 0) + 1
                  FROM celestin_candidate_revisions
                 WHERE workspace_id = %s AND project_id = %s AND producer_id = %s
                   AND candidate_id = %s
                """,
                (
                    self._scope.workspace_id,
                    self._scope.project_id,
                    delivery.producer_id,
                    candidate_id,
                ),
            )
            revisions[candidate_id] = _positive_int(row[0], "candidate_revision")
        return revisions

    def _receipt_candidates(
        self,
        occurrence_candidate_ids: tuple[str, ...],
        revisions: dict[str, int],
    ) -> tuple[DeliveryCandidateRevision, ...]:
        first = _first_occurrence_ordinals(occurrence_candidate_ids)
        return tuple(
            DeliveryCandidateRevision(candidate_id, revisions[candidate_id], first[candidate_id])
            for candidate_id in sorted(first, key=first.__getitem__)
        )

    def _delivery_provenance(
        self,
        delivery: ProducerDelivery,
        payload_hash: str,
        candidate_id: str,
        candidate_revision: int,
        occurrences: Sequence[tuple[int, ProducerOccurrence]],
    ) -> ProducerDeliveryProvenance:
        typed_occurrences: list[ProducerOccurrenceProvenance] = []
        conflicts: list[ProducerConflictReference] = []
        for ordinal, occurrence in occurrences:
            source_id = occurrence.source_id or delivery.source_id
            source_revision = occurrence.source_revision or delivery.source_revision
            occurred_at = occurrence.occurred_at or delivery.occurred_at
            evidence = tuple(item.to_evidence_source() for item in occurrence.evidence)
            typed_occurrences.append(
                ProducerOccurrenceProvenance(
                    ordinal=ordinal,
                    category=occurrence.category.value,
                    claim=occurrence.claim,
                    source_namespace=delivery.source_namespace,
                    source_id=source_id,
                    source_revision=source_revision,
                    occurred_at=occurred_at,
                    locator=occurrence.locator,
                    evidence=evidence,
                    candidate_id=candidate_id,
                    candidate_revision=candidate_revision,
                )
            )
            conflicts.extend(occurrence.conflicts)
        return ProducerDeliveryProvenance(
            schema_version=delivery.schema_version,
            producer_id=delivery.producer_id,
            source_namespace=delivery.source_namespace,
            delivery_id=delivery.delivery_id,
            payload_revision_id=delivery.payload_revision_id,
            payload_hash_version=PRODUCER_DELIVERY_HASH_VERSION,
            payload_hash=payload_hash,
            occurrences=tuple(typed_occurrences),
            conflicts=tuple(conflicts),
        )

    def _insert_candidate_revision(
        self,
        delivery: ProducerDelivery,
        candidate: KnowledgeCandidate,
        candidate_revision: int,
        provenance: ProducerDeliveryProvenance,
        conflicts: Sequence[ProducerConflictReference],
    ) -> None:
        principal = self._scope.principal
        user_id = self._scope.principal_id if principal.kind == "human" else None
        service_id = self._scope.principal_id if principal.kind == "service" else None
        self._execute(
            """
            INSERT INTO celestin_candidate_revisions
                (workspace_id, project_id, producer_id, candidate_id, candidate_revision,
                 category, certainty, claim, original_claim,
                 candidate_verification_status, candidate_created_at,
                 submitted_by_kind, submitted_by_issuer, submitted_by_subject,
                 submitted_by_user_id, submitted_by_service_identity_id,
                 conflict_declarations)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                self._scope.workspace_id,
                self._scope.project_id,
                delivery.producer_id,
                candidate.candidate_id,
                candidate_revision,
                candidate.category.value,
                candidate.certainty.value,
                candidate.claim,
                candidate.original_claim,
                candidate.verification_status.value,
                _db_timestamp(candidate.created_at),
                principal.kind,
                principal.issuer,
                principal.subject,
                user_id,
                service_id,
                _json([_conflict_dict(item) for item in conflicts]),
            ),
        )
        state = {
            "candidate": _candidate_to_dict(candidate),
            "producer_delivery": producer_delivery_to_dict(provenance),
        }
        self._execute(
            """
            INSERT INTO celestin_candidate_revision_payloads
                (workspace_id, project_id, producer_id, candidate_id,
                 candidate_revision, capture_state)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                self._scope.workspace_id,
                self._scope.project_id,
                delivery.producer_id,
                candidate.candidate_id,
                candidate_revision,
                _json(state),
            ),
        )

    def _insert_delivery_candidate_revision(
        self,
        delivery: ProducerDelivery,
        candidate_id: str,
        candidate_revision: int,
        first_occurrence_ordinal: int,
    ) -> None:
        self._execute(
            """
            INSERT INTO celestin_delivery_candidate_revisions
                (workspace_id, project_id, producer_id, source_namespace, delivery_id,
                 candidate_id, candidate_revision, first_occurrence_ordinal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                self._scope.workspace_id,
                self._scope.project_id,
                delivery.producer_id,
                delivery.source_namespace,
                delivery.delivery_id,
                candidate_id,
                candidate_revision,
                first_occurrence_ordinal,
            ),
        )

    def _insert_candidate_evidence_and_occurrences(
        self,
        delivery: ProducerDelivery,
        candidate: KnowledgeCandidate,
        candidate_revision: int,
        occurrences: Sequence[tuple[int, ProducerOccurrence]],
    ) -> None:
        evidence_ids: dict[EvidenceSource, str] = {}
        for source in candidate.evidence:
            evidence_id = str(uuid4())
            evidence_ids[source] = evidence_id
            self._execute(
                """
                INSERT INTO celestin_candidate_evidence_records
                    (workspace_id, project_id, evidence_record_id, evidence_type,
                     source_namespace, source_id, source_revision, locator, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._scope.workspace_id,
                    self._scope.project_id,
                    evidence_id,
                    source.evidence_type.value,
                    delivery.source_namespace,
                    source.source_id,
                    source.revision,
                    source.locator,
                    source.content_hash,
                ),
            )

        association_ordinal = 0
        for _input_ordinal, occurrence in occurrences:
            occurred_at = occurrence.occurred_at or delivery.occurred_at
            for reference in occurrence.evidence:
                source = reference.to_evidence_source()
                evidence_id = evidence_ids.get(source)
                if evidence_id is None:
                    raise ProducerWorkflowError(
                        "evidence_association_missing",
                        "Capture did not retain an occurrence evidence association",
                    )
                self._execute(
                    """
                    INSERT INTO celestin_candidate_occurrences
                        (workspace_id, project_id, producer_id, candidate_id,
                         candidate_revision, ordinal, evidence_record_id, source_occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        delivery.producer_id,
                        candidate.candidate_id,
                        candidate_revision,
                        association_ordinal,
                        evidence_id,
                        _db_timestamp(occurred_at) if occurred_at is not None else None,
                    ),
                )
                association_ordinal += 1

    def _review(
        self,
        producer_id: str,
        candidate_id: str,
        candidate_revision: int,
        status: ReviewStatus,
        note: str | None,
    ) -> CandidateReviewResult:
        self._require_permission("candidate:approve")
        if self._scope.principal.kind != "human":
            raise HostedAccessDenied("access denied")
        producer_id = _required_text(producer_id, "producer_id")
        candidate_id = _required_text(candidate_id, "candidate_id")
        candidate_revision = _positive_int(candidate_revision, "candidate_revision")
        note = _optional_text(note, "review_note", limit=2_000)
        reviewer_id = f"{self._scope.principal.issuer}:{self._scope.principal.subject}"
        event_type = "approved" if status is ReviewStatus.APPROVED else "rejected"
        try:
            with self._atomic():
                revision, _state = self._load_candidate_revision(
                    producer_id, candidate_id, candidate_revision
                )
                latest = self._load_latest_review(producer_id, candidate_id, candidate_revision)
                if latest is not None:
                    if latest[0] == event_type:
                        return CandidateReviewResult(
                            self._scope.project_key,
                            candidate_id,
                            candidate_revision,
                            _review_state(status),
                            f"{latest[3]}:{latest[4]}",
                            _utc_iso(latest[1]),
                            latest[2],
                            replayed=True,
                        )
                    raise ProducerWorkflowError(
                        "review_transition_invalid",
                        "candidate revision already has a different terminal review decision",
                    )
                if status is ReviewStatus.APPROVED and revision[7] == self._scope.principal_id:
                    raise ProducerWorkflowError(
                        "self_review_forbidden", "candidate submitter cannot approve their own revision"
                    )
                event = self._fetchone(
                    """
                    INSERT INTO celestin_candidate_review_events
                        (workspace_id, project_id, producer_id, candidate_id,
                         candidate_revision, event_type, reviewer_user_id, review_note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING event_at
                    """,
                    (
                        self._scope.workspace_id,
                        self._scope.project_id,
                        producer_id,
                        candidate_id,
                        candidate_revision,
                        event_type,
                        self._scope.principal_id,
                        note,
                    ),
                )
                if event is None:
                    raise ProducerWorkflowError("review_write_failed", "review event was not returned")
                return CandidateReviewResult(
                    self._scope.project_key,
                    candidate_id,
                    candidate_revision,
                    _review_state(status),
                    reviewer_id,
                    _utc_iso(event[0]),
                    note,
                )
        except ProducerWorkflowError:
            raise
        except Exception as exc:
            raise ProducerWorkflowError(
                "review_failed", "review event was rolled back"
            ) from exc

    def _load_candidate_revision(
        self, producer_id: str, candidate_id: str, candidate_revision: int
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        row = self._fetchone(
            """
            SELECT revision.producer_id, revision.category, revision.certainty,
                   revision.claim, revision.original_claim,
                   revision.candidate_verification_status,
                   revision.candidate_created_at, revision.submitted_by_user_id,
                   payload.capture_state
              FROM celestin_candidate_revisions AS revision
              JOIN celestin_candidate_revision_payloads AS payload
                USING (workspace_id, project_id, producer_id, candidate_id, candidate_revision)
             WHERE revision.workspace_id = %s AND revision.project_id = %s
               AND revision.producer_id = %s AND revision.candidate_id = %s
               AND revision.candidate_revision = %s
             FOR UPDATE OF revision
            """,
            (
                self._scope.workspace_id,
                self._scope.project_id,
                producer_id,
                candidate_id,
                candidate_revision,
            ),
        )
        if row is None:
            raise ProducerWorkflowError("candidate_not_found", "candidate revision was not found")
        state = _json_value(row[8])
        candidate_state = state.get("candidate")
        if not isinstance(candidate_state, dict):
            raise ProducerWorkflowError("candidate_integrity_error", "stored Capture state is invalid")
        if (
            candidate_state.get("candidate_id") != candidate_id
            or candidate_state.get("category") != row[1]
            or candidate_state.get("certainty") != row[2]
            or candidate_state.get("claim") != row[3]
            or candidate_state.get("verification_status") != row[5]
        ):
            raise ProducerWorkflowError(
                "candidate_integrity_error", "stored Capture state differs from candidate revision"
            )
        return tuple(row), state

    def _load_latest_review(
        self, producer_id: str, candidate_id: str, candidate_revision: int
    ) -> tuple[Any, ...] | None:
        return self._fetchone(
            """
            SELECT event.event_type, event.event_at, event.review_note,
                   reviewer.issuer, reviewer.subject, event.reviewer_user_id
              FROM celestin_candidate_review_events AS event
              JOIN celestin_users AS reviewer ON reviewer.id = event.reviewer_user_id
             WHERE event.workspace_id = %s AND event.project_id = %s
               AND event.producer_id = %s AND event.candidate_id = %s
               AND event.candidate_revision = %s
             ORDER BY event.event_number DESC LIMIT 1
            """,
            (
                self._scope.workspace_id,
                self._scope.project_id,
                producer_id,
                candidate_id,
                candidate_revision,
            ),
        )

    def _conversion_payload(
        self,
        candidate_revision: int,
        candidate: KnowledgeCandidate,
        provenance: ProducerDeliveryProvenance,
        knowledge_type: str,
        reviewer_id: str,
        approved_at: str,
    ) -> dict[str, object]:
        evidence_occurrences: list[dict[str, object]] = []
        for occurrence in provenance.occurrences:
            for evidence in occurrence.evidence:
                evidence_occurrences.append(
                    {
                        "content_hash": evidence.content_hash,
                        "evidence_type": evidence.evidence_type.value,
                        "locator": evidence.locator or occurrence.locator,
                        "ordinal": len(evidence_occurrences),
                        "source_id": evidence.source_id,
                        "source_namespace": occurrence.source_namespace,
                        "source_occurred_at": occurrence.occurred_at,
                        "source_revision": evidence.revision or occurrence.source_revision,
                    }
                )
        conflicts = [_conflict_dict(item) for item in provenance.conflicts]
        return {
            "schema_version": 1,
            "project_id": self._scope.project_key,
            "producer_id": provenance.producer_id,
            "candidate_id": candidate.candidate_id,
            "candidate_revision": candidate_revision,
            "category": candidate.category.value,
            "knowledge_type": knowledge_type,
            "certainty": candidate.certainty.value,
            "claim": candidate.claim,
            "original_claim": candidate.original_claim,
            "candidate_verification_status": candidate.verification_status.value,
            "candidate_created_at": candidate.created_at,
            "reviewer_id": reviewer_id,
            "approved_at": approved_at,
            "evidence_occurrences": evidence_occurrences,
            "conflicts": conflicts,
            "supersedes_knowledge_id": None,
        }

    def _knowledge_id(
        self, producer_id: str, candidate_id: str, candidate_revision: int, conversion_hash: str
    ) -> str:
        identity = "\0".join(
            (
                str(self._scope.workspace_id),
                str(self._scope.project_id),
                producer_id,
                candidate_id,
                str(candidate_revision),
                CONVERSION_HASH_VERSION_V1,
                conversion_hash,
            )
        )
        return "knowledge-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _candidate_to_dict(candidate: KnowledgeCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "project_id": candidate.project_id,
        "category": candidate.category.value,
        "claim": candidate.claim,
        "source_references": [
            {
                "source_type": source.source_type.value,
                "source_id": source.source_id,
                "source_timestamp": source.source_timestamp,
                "source_revision": source.source_revision,
                "locator": source.locator,
            }
            for source in candidate.source_references
        ],
        "evidence": [
            {
                "evidence_type": evidence.evidence_type.value,
                "source_id": evidence.source_id,
                "locator": evidence.locator,
                "revision": evidence.revision,
                "content_hash": evidence.content_hash,
            }
            for evidence in candidate.evidence
        ],
        "status": candidate.status.value,
        "certainty": candidate.certainty.value,
        "verification_status": candidate.verification_status.value,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
        "conflict_key": candidate.conflict_key,
        "conflicts_with": list(candidate.conflicts_with),
        "original_claim": candidate.original_claim,
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": candidate.reviewed_at,
        "review_note": candidate.review_note,
    }


def _candidate_from_state(state: dict[str, Any]) -> KnowledgeCandidate:
    try:
        raw = state["candidate"]
        if not isinstance(raw, dict):
            raise TypeError
        return KnowledgeCandidate(
            candidate_id=raw["candidate_id"],
            project_id=raw["project_id"],
            category=CandidateCategory(raw["category"]),
            claim=raw["claim"],
            source_references=tuple(
                CaptureSourceReference(
                    source_type=CaptureSourceType(item["source_type"]),
                    source_id=item["source_id"],
                    source_timestamp=item.get("source_timestamp"),
                    source_revision=item.get("source_revision"),
                    locator=item.get("locator"),
                )
                for item in raw["source_references"]
            ),
            evidence=tuple(
                EvidenceSource(
                    evidence_type=EvidenceType(item["evidence_type"]),
                    source_id=item["source_id"],
                    locator=item.get("locator"),
                    revision=item.get("revision"),
                    content_hash=item.get("content_hash"),
                )
                for item in raw["evidence"]
            ),
            status=ReviewStatus(raw["status"]),
            certainty=CandidateCertainty(raw["certainty"]),
            verification_status=VerificationStatus(raw["verification_status"]),
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            conflict_key=raw.get("conflict_key"),
            conflicts_with=tuple(raw.get("conflicts_with", ())),
            original_claim=raw.get("original_claim"),
            reviewed_by=raw.get("reviewed_by"),
            reviewed_at=raw.get("reviewed_at"),
            review_note=raw.get("review_note"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProducerWorkflowError(
            "candidate_integrity_error", "stored Capture candidate is invalid"
        ) from exc


def _candidate_ref_dict(candidate: DeliveryCandidateRevision) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_revision": candidate.candidate_revision,
        "first_occurrence_ordinal": candidate.first_occurrence_ordinal,
    }


def _first_occurrence_ordinals(candidate_ids: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for ordinal, candidate_id in enumerate(candidate_ids):
        result.setdefault(candidate_id, ordinal)
    return result


def _conflict_dict(conflict: ProducerConflictReference) -> dict[str, object]:
    return {
        "producer_id": conflict.producer_id,
        "candidate_id": conflict.candidate_id,
        "candidate_revision": conflict.candidate_revision,
    }


def _conflict_label(conflict: ProducerConflictReference) -> str:
    return f"{conflict.producer_id}/{conflict.candidate_id}@{conflict.candidate_revision}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored JSON value must be an object")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProducerWorkflowError("invalid_field", f"{field} must be non-empty text")
    return value


def _optional_text(value: object, field: str, *, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value or len(value) > limit:
        raise ProducerWorkflowError("invalid_field", f"{field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProducerWorkflowError("invalid_field", f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProducerWorkflowError("invalid_field", f"{field} must be a non-negative integer")
    return value


def _db_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProducerWorkflowError(
            "invalid_timestamp", "timestamp must be timezone-aware ISO 8601"
        ) from exc
    if parsed.tzinfo is None:
        raise ProducerWorkflowError("invalid_timestamp", "timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        value = _db_timestamp(value)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ProducerWorkflowError("invalid_timestamp", "stored timestamp is not timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _close_cursor(cursor: Any) -> None:
    close = getattr(cursor, "close", None)
    if callable(close):
        close()
