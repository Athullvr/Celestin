from __future__ import annotations

from dataclasses import dataclass

from orbit.evidence.model import (
    CaptureKnowledgeProvenance,
    CaptureSourceProvenance,
    EvidenceRecord,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    ProducerDeliveryProvenance,
    ProducerOccurrenceProvenance,
    ReferenceStatus,
    VerificationStatus,
)
from orbit.project_state.knowledge_read import (
    KnowledgeCoverage,
    KnowledgeReadFailure,
    KnowledgeReadFailureKind,
    KnowledgeReadOutcome,
    KnowledgeReadResult,
)
from orbit.retrieval.knowledge import KnowledgeRetrievalService


NOW = "2026-11-01T10:00:00.000000Z"


def knowledge_bundle(project: str = "p1", knowledge_id: str = "k-1") -> KnowledgeBundle:
    evidence = EvidenceRecord(
        "e-1", project, EvidenceType.REPOSITORY_FILE, "repo-7", "README.md:8",
        "a1b2c3", "sha256:" + "a" * 64, NOW, ReferenceStatus.UNRESOLVED,
    )
    producer_delivery = ProducerDeliveryProvenance(
        schema_version=1,
        producer_id="producer-1",
        source_namespace="git",
        delivery_id="delivery-1",
        payload_revision_id="revision-1",
        payload_hash_version="celestin-producer-delivery-v1+jcs-rfc8785+sha256",
        payload_hash="b" * 64,
        occurrences=(ProducerOccurrenceProvenance(
            ordinal=0,
            category="decision",
            claim="Use the bounded queue for project jobs.",
            source_namespace="git",
            source_id="repo-7",
            source_revision="a1b2c3",
            occurred_at=NOW,
            locator="README.md:8",
            evidence=(evidence_source(),),
            candidate_id="candidate-1",
            candidate_revision=1,
        ),),
    )
    provenance = CaptureKnowledgeProvenance(
        candidate_id="candidate-1",
        project_id=project,
        category="decision",
        certainty="unqualified",
        review_status="approved",
        candidate_verification_status="unverified",
        source_references=(CaptureSourceProvenance(
            "execution_report", "run-9", NOW, "a1b2c3", "README.md:8"
        ),),
        candidate_created_at=NOW,
        candidate_updated_at=NOW,
        reviewed_by="reviewer",
        reviewed_at=NOW,
        producer_delivery=producer_delivery,
    )
    record = KnowledgeRecord(
        knowledge_id,
        project,
        KnowledgeType.DECISION,
        "Use the bounded queue for project jobs.",
        NOW,
        NOW,
        VerificationStatus.UNVERIFIED,
        capture_provenance=provenance,
    )
    return KnowledgeBundle(record, (evidence,))


def evidence_source():
    from orbit.evidence.model import EvidenceSource

    return EvidenceSource(
        EvidenceType.REPOSITORY_FILE,
        "repo-7",
        "README.md:8",
        "a1b2c3",
        "sha256:" + "a" * 64,
    )


@dataclass(frozen=True)
class Match:
    knowledge_id: str
    project: str
    claim: str
    updated_at: str | None
    score: float


@dataclass(frozen=True)
class Page:
    matches: tuple[Match, ...]
    tier: str = "fts"


class Search:
    def __init__(self, matches: tuple[Match, ...] = ()) -> None:
        self.matches = matches
        self.calls: list[tuple[str, str, int, bool]] = []

    def search_knowledge(self, project: str, query: str, limit: int, *, relax: bool) -> Page:
        self.calls.append((project, query, limit, relax))
        return Page(self.matches)


def test_retrieval_joins_fts_hits_to_read_ids_and_preserves_typed_provenance():
    bundle = knowledge_bundle()
    read = KnowledgeReadResult.succeeded(
        "p1", [bundle], coverage=KnowledgeCoverage.PARTIAL, limitations=["page 2 unavailable"]
    )
    search = Search((
        Match("k-1", "p1", bundle.record.claim, NOW, -0.8),
        Match("ghost", "p1", "unbound result", NOW, -0.5),
        Match("foreign-id", "p2", bundle.record.claim, NOW, -0.2),
    ))

    result = KnowledgeRetrievalService(search).retrieve(
        read, "bounded queue", token_budget=10_000
    )

    assert search.calls == [("p1", "bounded queue", 20, True)]
    assert result.knowledge_read is read
    assert result.knowledge_read.coverage is KnowledgeCoverage.PARTIAL
    assert result.search_outcome == "succeeded"
    assert result.context_bundle is not None
    assert [item.record_id for item in result.context_bundle.items] == ["knowledge:k-1"]
    state = result.context_bundle.items[0].knowledge_state
    assert state is not None
    assert state.capture_provenance is not None
    assert state.capture_provenance.producer_delivery == bundle.record.capture_provenance.producer_delivery
    assert state.evidence[0].evidence_id == "e-1"
    assert {(item.knowledge_id, item.reason) for item in result.exclusions} == {
        ("ghost", "not_in_knowledge_read"),
        ("foreign-id", "project_mismatch"),
    }


def test_empty_failed_and_scope_mismatch_reads_are_not_collapsed_or_searched():
    search = Search()
    service = KnowledgeRetrievalService(search)
    outcomes = (
        KnowledgeReadResult.succeeded("p1"),
        KnowledgeReadResult.failed(
            "p1", KnowledgeReadFailure(KnowledgeReadFailureKind.UNAVAILABLE, "read failed")
        ),
        KnowledgeReadResult.scope_mismatch("p1"),
    )

    results = [service.retrieve(read, "query") for read in outcomes]

    assert [result.knowledge_read.outcome for result in results] == [
        KnowledgeReadOutcome.SUCCEEDED,
        KnowledgeReadOutcome.FAILED,
        KnowledgeReadOutcome.SCOPE_MISMATCH,
    ]
    assert [result.search_outcome for result in results] == ["succeeded", "not_run", "not_run"]
    assert results[0].context_bundle is not None and results[0].context_bundle.items == ()
    assert results[1].context_bundle is None and results[2].context_bundle is None
    assert search.calls == [("p1", "query", 20, True)]
