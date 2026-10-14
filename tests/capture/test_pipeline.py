from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbit.capture import (
    CandidateCategory,
    CandidateCertainty,
    CandidateNotFound,
    CaptureEvent,
    CaptureInput,
    CaptureRepositoryError,
    CaptureSourceType,
    CaptureValidationError,
    InMemoryCaptureRepository,
    InvalidReviewTransition,
    KnowledgeCapturePipeline,
    ReviewStatus,
    SensitiveContentRejected,
    evidence_sources_for,
)
from orbit.evidence.model import EvidenceSource, EvidenceType, VerificationStatus


NOW = datetime(2026, 10, 15, 0, 40, tzinfo=timezone.utc)


def pipeline(project="celestin", repository=None):
    return KnowledgeCapturePipeline(
        project,
        repository,
        clock=lambda: NOW,
    )


def request(
    content,
    *,
    project="celestin",
    source_id="summary-1",
    source_type=CaptureSourceType.CONVERSATION_SUMMARY,
    evidence=(),
):
    return CaptureInput(
        project_id=project,
        source_type=source_type,
        source_id=source_id,
        source_timestamp="2026-10-14T23:00:00Z",
        source_revision="rev-123",
        content=content,
        evidence=evidence,
    )


def test_labeled_input_extracts_every_supported_category_with_source_lines():
    text = "\n".join(
        (
            "Decision [storage]: use SQLite for local persistence because it works offline",
            "Discovery: FTS5 supports strict and relaxed search",
            "Bug fix: corrected path normalization after symlink resolution",
            "Completed: added project authorization checks",
            "Incomplete: finish PostgreSQL adapter integration",
            "Blocker: waiting for the shared storage contract",
            "Constraint: preserve legacy MCP tool arguments",
            "Implementation detail: read repository files from pinned Git blobs",
        )
    )

    result = pipeline().capture(request(text))

    assert {item.category for item in result.candidates} == set(CandidateCategory)
    assert len(result.candidates) == 8
    assert all(item.status is ReviewStatus.PENDING for item in result.candidates)
    assert all(item.verification_status is VerificationStatus.UNVERIFIED for item in result.candidates)
    assert "because it works offline" in next(
        item.claim for item in result.candidates if item.category is CandidateCategory.DECISION
    )
    assert {item.source_references[0].locator for item in result.candidates} == {
        f"line:{number}" for number in range(1, 9)
    }


def test_structured_event_preserves_source_and_capability_one_evidence():
    evidence = EvidenceSource(EvidenceType.GIT_COMMIT, "commit-abc", revision="abc")
    event = CaptureEvent(
        CandidateCategory.BUG_FIX,
        "Fixed the cache key collision",
        evidence=(evidence,),
        locator="report:fix-2",
    )

    queue = pipeline()
    candidate = queue.capture(
        request(
            (event,),
            source_type=CaptureSourceType.EXECUTION_REPORT,
            source_id="run-42",
        )
    ).candidates[0]

    assert candidate.source_references[0].source_type is CaptureSourceType.EXECUTION_REPORT
    assert candidate.source_references[0].source_id == "run-42"
    assert candidate.source_references[0].locator == "report:fix-2"
    assert candidate.evidence == (evidence,)
    with pytest.raises(InvalidReviewTransition):
        evidence_sources_for(candidate, target_project="celestin")
    approved = queue.approve("celestin", candidate.candidate_id, reviewer_id="reviewer-1")
    mapped = evidence_sources_for(approved, target_project="celestin")
    assert EvidenceSource(
        EvidenceType.OTHER,
        "run-42",
        locator="execution_report: report:fix-2",
        revision="rev-123",
    ) in mapped
    assert evidence in mapped


def test_evidence_mapping_requires_a_valid_matching_target_project():
    queue = pipeline("alpha")
    candidate = queue.capture(request("Decision: use SQLite", project="alpha")).candidates[0]
    approved = queue.approve("alpha", candidate.candidate_id, reviewer_id="reviewer-1")

    with pytest.raises(CaptureValidationError, match="target_project"):
        evidence_sources_for(approved, target_project=" ")
    with pytest.raises(CaptureValidationError, match="does not match"):
        evidence_sources_for(approved, target_project="beta")

    assert evidence_sources_for(approved, target_project="alpha")


@pytest.mark.parametrize(
    "bad_request",
    [
        lambda: request("  "),
        lambda: request("Decision: x", project=" "),
        lambda: request("Decision: x", source_id=""),
        lambda: request((), source_id="source"),
        lambda: request("Decision: x", source_type="chat"),
    ],
)
def test_empty_or_malformed_input_is_rejected(bad_request):
    with pytest.raises(CaptureValidationError):
        pipeline().capture(bad_request())


def test_queue_rejects_mismatched_project_without_accepting_candidates():
    queue = pipeline("alpha")

    with pytest.raises(CaptureValidationError, match="does not match"):
        queue.capture(request("Decision: use SQLite", project="beta"))
    assert queue.list_candidates("alpha") == ()


def test_source_identifiers_are_required_and_input_size_is_bounded():
    with pytest.raises(CaptureValidationError, match="source_id"):
        pipeline().capture(request("Decision: choose X", source_id="  "))
    with pytest.raises(CaptureValidationError, match="exceeds"):
        pipeline().capture(request("x" * 100_001))


def test_repeated_and_normalized_duplicate_input_is_idempotent():
    queue = pipeline()
    first = queue.capture(request("Decision: Use SQLite for local storage."))
    first_candidate = first.candidates[0]
    repeated = queue.capture(request("  decision:   use sqlite FOR local storage.  "))
    merged = queue.capture(
        request(
            "Decision: Use SQLite for local storage.",
            source_id="summary-2",
            source_type=CaptureSourceType.EXECUTION_REPORT,
        )
    )

    assert repeated.duplicate_count == 1
    assert repeated.candidates[0] == first_candidate
    assert merged.duplicate_count == 1
    assert merged.candidates[0].candidate_id == first_candidate.candidate_id
    assert len(merged.candidates[0].source_references) == 2
    assert len(queue.list_candidates("celestin")) == 1


def test_explicit_conflicts_are_linked_without_selecting_a_winner():
    queue = pipeline()
    sqlite = queue.capture(request("Decision [storage]: Use SQLite.")).candidates[0]
    postgres = queue.capture(
        request("Decision [storage]: Use PostgreSQL.", source_id="summary-2")
    ).candidates[0]

    sqlite_after = queue.get_candidate("celestin", sqlite.candidate_id)
    postgres_after = queue.get_candidate("celestin", postgres.candidate_id)

    assert sqlite_after.conflicts_with == (postgres.candidate_id,)
    assert postgres_after.conflicts_with == (sqlite.candidate_id,)
    assert sqlite_after.status is postgres_after.status is ReviewStatus.PENDING
    assert all(item.verification_status is VerificationStatus.UNVERIFIED for item in (sqlite_after, postgres_after))


def test_uncertain_completion_stays_uncertain_unverified_and_pending():
    queue = pipeline()
    result = queue.capture(
        request("Completed: the migration might be finished, but needs a check")
    )
    candidate = result.candidates[0]
    uncategorized = queue.capture(request("The migration is complete and tests passed."))

    assert candidate.category is CandidateCategory.COMPLETED_WORK
    assert candidate.certainty is CandidateCertainty.UNCERTAIN
    assert candidate.status is ReviewStatus.PENDING
    assert candidate.verification_status is VerificationStatus.UNVERIFIED
    assert uncategorized.candidates == ()


def test_secret_like_candidate_is_suppressed_without_storing_its_value():
    queue = pipeline()
    secret = "sk_live_example_secret_value_12345"
    result = queue.capture(
        request(f"Constraint: API_KEY={secret} is required for the service")
    )

    assert result.candidates == ()
    assert len(result.suppressed) == 1
    assert result.suppressed[0].reason == "secret_like_content"
    assert secret not in repr(result)
    assert queue.list_candidates("celestin") == ()


def test_review_edit_approval_rejection_and_needs_evidence_are_scoped_and_unverified():
    queue = pipeline()
    extracted = queue.capture(
        request(
            (
                CaptureEvent(CandidateCategory.DECISION, "Use SQLite"),
                CaptureEvent(CandidateCategory.BLOCKER, "Need a storage contract"),
                CaptureEvent(CandidateCategory.DISCOVERY, "Captured discovery"),
            )
        )
    ).candidates
    decision = extracted[0]
    blocker = extracted[1]
    discovery = extracted[2]

    edited = queue.edit_candidate(
        "celestin", decision.candidate_id, "Use SQLite for local state", reviewer_id="reviewer-1"
    )
    needs_evidence = queue.request_evidence(
        "celestin", decision.candidate_id, reviewer_id="reviewer-1", note="Check deployment target"
    )
    approved = queue.approve(
        "celestin", decision.candidate_id, reviewer_id="reviewer-1", note="Reviewed"
    )
    rejected = queue.reject(
        "celestin", blocker.candidate_id, reviewer_id="reviewer-2", note="No longer blocked"
    )

    assert edited.original_claim == "Use SQLite"
    assert edited.reviewed_by == "reviewer-1"
    assert needs_evidence.status is ReviewStatus.NEEDS_EVIDENCE
    assert approved.status is ReviewStatus.APPROVED
    assert approved.verification_status is VerificationStatus.UNVERIFIED
    assert rejected.status is ReviewStatus.REJECTED
    assert {item.status for item in queue.list_candidates("celestin", ReviewStatus.APPROVED)} == {
        ReviewStatus.APPROVED
    }
    with pytest.raises(InvalidReviewTransition):
        queue.edit_candidate("celestin", decision.candidate_id, "Changed", reviewer_id="reviewer-1")
    with pytest.raises(SensitiveContentRejected):
        queue.edit_candidate(
            "celestin", discovery.candidate_id, "Password=secret_value_123", reviewer_id="reviewer-2"
        )


def test_project_isolation_and_foreign_scope_reads_are_rejected():
    shared = InMemoryCaptureRepository()
    alpha = pipeline("alpha", shared)
    beta = pipeline("beta", shared)
    alpha_candidate = alpha.capture(request("Discovery: alpha only", project="alpha")).candidates[0]
    beta.capture(request("Discovery: beta only", project="beta"))

    assert [item.claim for item in alpha.list_candidates("alpha")] == ["alpha only"]
    assert [item.claim for item in beta.list_candidates("beta")] == ["beta only"]
    with pytest.raises(CaptureValidationError, match="outside"):
        alpha.list_candidates("beta")
    with pytest.raises(CandidateNotFound):
        beta.get_candidate("beta", alpha_candidate.candidate_id)


def test_capture_output_is_deterministic_for_the_same_input_and_clock():
    source = request("Discovery: deterministic extraction")

    first = pipeline().capture(source)
    second = pipeline().capture(source)

    assert first == second


def test_repository_failures_are_reported_without_claiming_capture_succeeded():
    class BrokenRepository:
        def get(self, project_id, candidate_id):
            return None

        def list(self, project_id, status=None):
            return ()

        def put(self, candidate):
            raise OSError("repository write failed")

    with pytest.raises(CaptureRepositoryError, match="save review candidate"):
        pipeline(repository=BrokenRepository()).capture(request("Decision: capture this"))


def test_conflict_group_links_all_alternatives_without_erasing_claims():
    queue = pipeline()
    sqlite = queue.capture(request("Decision [storage]: Use SQLite.")).candidates[0]
    postgres = queue.capture(
        request("Decision [storage]: Use PostgreSQL.", source_id="summary-2")
    ).candidates[0]

    mysql = queue.capture(
        request("Decision [storage]: Use MySQL.", source_id="summary-3")
    ).candidates[0]
    assert set(queue.get_candidate("celestin", sqlite.candidate_id).conflicts_with) == {
        postgres.candidate_id, mysql.candidate_id
    }
    assert set(queue.get_candidate("celestin", postgres.candidate_id).conflicts_with) == {
        sqlite.candidate_id, mysql.candidate_id
    }
    assert set(queue.get_candidate("celestin", mysql.candidate_id).conflicts_with) == {
        sqlite.candidate_id, postgres.candidate_id
    }
    assert len(queue.list_candidates("celestin")) == 3
