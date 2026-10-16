from __future__ import annotations

import json
from dataclasses import replace

import pytest

from orbit.database.engine import connect
from orbit.evidence.model import (
    CaptureKnowledgeProvenance,
    CaptureSourceProvenance,
    EvidenceRecord,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    LifecycleStatus,
    ReferenceStatus,
    VerificationStatus,
)
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval.context_builder import build_context_bundle
from orbit.retrieval.knowledge_state import (
    KNOWLEDGE_STATE_SCHEMA_VERSION,
    KnowledgeStateEnvelope,
    KnowledgeStateScopeError,
)
from orbit.retrieval.ranking import RetrievalCandidate
from orbit.retrieval.service import RetrievalService


def knowledge_bundle(
    project: str = "alpha",
    *,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
    conflicts_with: tuple[str, ...] = ("candidate-elsewhere",),
) -> KnowledgeBundle:
    provenance = CaptureKnowledgeProvenance(
        candidate_id="candidate-1",
        project_id=project,
        category="decision",
        certainty="high",
        review_status="approved",
        candidate_verification_status="unverified",
        source_references=(
            CaptureSourceProvenance(
                source_type="conversation_summary",
                source_id="conversation-7",
                occurred_at="2026-10-14T23:10:00Z",
                revision="rev-3",
                locator="summary:decision-1",
            ),
        ),
        candidate_created_at="2026-10-15T01:00:00Z",
        candidate_updated_at="2026-10-15T02:00:00Z",
        original_claim="Original reviewed claim.",
        reviewed_by="reviewer-label",
        reviewed_at="2026-10-15T02:00:00Z",
        review_note="checked against the cited test",
        conflicts_with=conflicts_with,
    )
    record = KnowledgeRecord(
        knowledge_id="knowledge-1",
        project=project,
        knowledge_type=KnowledgeType.DECISION,
        claim="Use SQLite for the local source of truth.",
        created_at="2026-10-15T01:00:00Z",
        updated_at="2026-10-15T02:00:00Z",
        verification_status=status,
        lifecycle_status=LifecycleStatus.CURRENT,
        supersedes_id="knowledge-old",
        checked_at="2026-10-15T02:00:00Z" if status is not VerificationStatus.UNVERIFIED else None,
        checked_by="reviewer-label" if status is not VerificationStatus.UNVERIFIED else None,
        check_note="checked against the cited test" if status is not VerificationStatus.UNVERIFIED else None,
        capture_provenance=provenance,
    )
    evidence = EvidenceRecord(
        evidence_id="evidence-1",
        project=project,
        evidence_type=EvidenceType.TEST_RESULT,
        source_id="tests/test_storage.py::test_local_mode",
        locator="tests/test_storage.py::test_local_mode",
        revision="commit-abc",
        content_hash="sha256:abc123",
        captured_at="2026-10-15T01:01:00Z",
        reference_status=ReferenceStatus.AVAILABLE,
        verification_status=VerificationStatus.VERIFIED,
        checked_at="2026-10-15T02:00:00Z",
        checked_by="reviewer-label",
        check_note="test passed",
    )
    return KnowledgeBundle(record=record, evidence=(evidence,))


@pytest.mark.parametrize("status", list(VerificationStatus))
def test_verification_state_is_preserved_and_remains_separate_from_retrieval_status(status):
    state = KnowledgeStateEnvelope.from_bundle(knowledge_bundle(status=status))

    assert state.verification_status is status
    assert state.as_dict()["verification_status"] == status.value
    assert state.as_dict()["schema_version"] == KNOWLEDGE_STATE_SCHEMA_VERSION == 1


def test_approved_capture_does_not_imply_verified_knowledge():
    state = KnowledgeStateEnvelope.from_bundle(
        knowledge_bundle(status=VerificationStatus.UNVERIFIED)
    )

    assert state.capture_provenance.review_status == "approved"
    assert state.verification_status is VerificationStatus.UNVERIFIED


def test_legacy_knowledge_record_keeps_missing_metadata_unrecorded():
    record = KnowledgeRecord(
        knowledge_id="legacy-knowledge",
        project="alpha",
        knowledge_type=KnowledgeType.DISCOVERY,
        claim="A legacy stored claim.",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    state = KnowledgeStateEnvelope.from_bundle(KnowledgeBundle(record, ()))

    assert state.capture_provenance is None
    assert state.evidence == ()
    assert state.checked_at is state.checked_by is state.check_note is None
    assert state.reconstruction_assessment is None
    assert state.as_dict()["capture_provenance"] is None


def test_capability_one_evidence_and_capture_provenance_are_preserved_exactly():
    state = KnowledgeStateEnvelope.from_bundle(knowledge_bundle())
    encoded = state.as_dict()

    assert state.knowledge_id == "knowledge-1"
    assert state.claim == "Use SQLite for the local source of truth."
    assert state.knowledge_type is KnowledgeType.DECISION
    assert state.capture_provenance.candidate_id == "candidate-1"
    assert state.knowledge_id != state.capture_provenance.candidate_id
    assert state.reconstruction_assessment is None
    assert state.supersedes_id == "knowledge-old"
    assert state.superseded_by_id is None
    assert encoded["evidence"] == [
        {
            "evidence_id": "evidence-1",
            "evidence_type": "test_result",
            "source_id": "tests/test_storage.py::test_local_mode",
            "locator": "tests/test_storage.py::test_local_mode",
            "revision": "commit-abc",
            "content_hash": "sha256:abc123",
            "captured_at": "2026-10-15T01:01:00Z",
            "reference_status": "available",
            "verification_status": "verified",
            "checked_at": "2026-10-15T02:00:00Z",
            "checked_by": "reviewer-label",
            "check_note": "test passed",
        }
    ]
    provenance = encoded["capture_provenance"]
    assert provenance["source_references"] == [
        {
            "source_type": "conversation_summary",
            "source_id": "conversation-7",
            "occurred_at": "2026-10-14T23:10:00Z",
            "revision": "rev-3",
            "locator": "summary:decision-1",
        }
    ]
    assert provenance["category"] == "decision"
    assert provenance["certainty"] == "high"
    assert provenance["candidate_verification_status"] == "unverified"
    assert provenance["candidate_created_at"] == "2026-10-15T01:00:00Z"
    assert provenance["candidate_updated_at"] == "2026-10-15T02:00:00Z"
    assert provenance["reviewed_at"] == "2026-10-15T02:00:00Z"
    assert provenance["original_claim"] == "Original reviewed claim."
    assert provenance["reviewed_by"] == "reviewer-label"
    assert provenance["review_note"] == "checked against the cited test"
    # The reference is retained as a one-way source link; no reverse conflict is inferred.
    assert provenance["conflicts_with"] == ["candidate-elsewhere"]


def test_missing_conflict_links_stay_empty_and_schema_versions_are_checked():
    state = KnowledgeStateEnvelope.from_bundle(knowledge_bundle(conflicts_with=()))

    assert state.capture_provenance.conflicts_with == ()
    assert state.as_dict()["capture_provenance"]["conflicts_with"] == []
    with pytest.raises(ValueError, match="schema_version"):
        replace(state, schema_version=2)
    with pytest.raises(ValueError, match="schema_version"):
        replace(state, schema_version=1.0)


def test_legacy_context_omits_optional_knowledge_state():
    candidate = RetrievalCandidate(
        record_id="message-1",
        project_id="alpha",
        source_id="message-1",
        content="Legacy retrieved content.",
        timestamp=None,
        relevance_score=-1.0,
        record_kind="chat_message",
    )

    bundle = build_context_bundle([candidate], project_id="alpha")
    serialized = json.loads(bundle.rendered_context)

    assert bundle.items[0].knowledge_state is None
    assert "knowledge_state" not in bundle.items[0].as_dict()
    assert "knowledge_state" not in serialized


def test_knowledge_state_is_serialized_and_counted_in_the_context_budget():
    candidate = RetrievalCandidate(
        record_id="message-1",
        project_id="alpha",
        source_id="message-1",
        content="SQLite is the local source of truth.",
        timestamp=None,
        relevance_score=-1.0,
        record_kind="chat_message",
        knowledge_state=KnowledgeStateEnvelope.from_bundle(knowledge_bundle()),
    )
    state_less = build_context_bundle(
        [replace(candidate, knowledge_state=None)], project_id="alpha", token_budget=10_000
    )
    stateful = build_context_bundle([candidate], project_id="alpha", token_budget=10_000)
    rendered = json.loads(stateful.rendered_context)

    assert rendered["knowledge_state"]["schema_version"] == 1
    assert rendered["knowledge_state"]["evidence"][0]["source_id"] == (
        "tests/test_storage.py::test_local_mode"
    )
    assert stateful.token_count == len(stateful.rendered_context.encode("utf-8"))
    assert stateful.token_count > state_less.token_count

    limited = build_context_bundle(
        [candidate], project_id="alpha", token_budget=state_less.token_count
    )
    assert limited.items == ()
    assert limited.excluded[0].reason == "token_budget"


class FakeKnowledgeStateReader:
    def __init__(self, bundles: dict[tuple[str, str, str], KnowledgeBundle]):
        self.bundles = bundles
        self.calls: list[tuple[str, str, str]] = []

    def get_for_candidate(self, project_id: str, record_kind: str, record_id: str):
        key = (project_id, record_kind, record_id)
        self.calls.append(key)
        return self.bundles.get(key)


def test_reader_is_project_scoped_and_does_not_change_candidate_order(tmp_path):
    connection = connect(tmp_path / "knowledge-state.db")
    messages = ChatMessageRepository(connection)
    alpha_first = messages.insert("alpha", "conversation-a", "user", "retrieval-marker first")
    alpha_second = messages.insert("alpha", "conversation-a", "assistant", "retrieval-marker second")
    decisions = DecisionRepository(connection)
    approved = decisions.save(
        "alpha", "approved-key", "retrieval-marker approved choice", alpha_first, "approved"
    )
    draft = decisions.save("alpha", "draft-key", "retrieval-marker draft choice")
    deprecated = decisions.save(
        "alpha", "deprecated-key", "retrieval-marker deprecated choice", status="deprecated"
    )
    beta_id = messages.insert("beta", "conversation-b", "user", "retrieval-marker private")
    reader = FakeKnowledgeStateReader(
        {
            ("alpha", "chat_message", str(alpha_first)): knowledge_bundle("alpha"),
            ("beta", "chat_message", str(beta_id)): knowledge_bundle("beta"),
        }
    )

    baseline = RetrievalService(connection).retrieve_context("alpha", "retrieval-marker", 10_000)
    enriched = RetrievalService(
        connection, knowledge_state_reader=reader
    ).retrieve_context("alpha", "retrieval-marker", 10_000)

    baseline_order = [(item.record_id, item.relevance_score) for item in baseline.items]
    enriched_order = [(item.record_id, item.relevance_score) for item in enriched.items]
    assert enriched_order == baseline_order
    assert {item.record_id for item in enriched.items} == {
        str(alpha_first), str(alpha_second), f"decision:{approved['id']}"
    }
    assert {item.record_id for item in enriched.excluded} == {
        f"decision:{draft['id']}", f"decision:{deprecated['id']}"
    }
    assert {item.reason for item in enriched.excluded} == {"draft_status", "deprecated_status"}
    assert reader.calls and all(project == "alpha" for project, _, _ in reader.calls)
    assert next(item for item in enriched.items if item.record_id == str(alpha_first)).knowledge_state
    assert "beta" not in enriched.rendered_context
    assert all(item.project_id == "alpha" for item in enriched.items)
    connection.close()


def test_reader_rejects_a_bundle_from_another_project(tmp_path):
    connection = connect(tmp_path / "foreign-knowledge-state.db")
    message_id = ChatMessageRepository(connection).insert(
        "alpha", "conversation-a", "user", "retrieval-marker"
    )
    reader = FakeKnowledgeStateReader(
        {("alpha", "chat_message", str(message_id)): knowledge_bundle("beta")}
    )
    service = RetrievalService(connection, knowledge_state_reader=reader)

    with pytest.raises(KnowledgeStateScopeError, match="requested project"):
        service.retrieve_context("alpha", "retrieval-marker", 10_000)
    connection.close()
