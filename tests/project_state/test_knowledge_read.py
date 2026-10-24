from __future__ import annotations

import dataclasses

import pytest

from orbit.evidence.model import (
    CaptureKnowledgeProvenance,
    EvidenceRecord,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    ReferenceStatus,
)
from orbit.project_state.knowledge_read import (
    REPORTED_COMPLETE_LIMITATION,
    KnowledgeCoverage,
    KnowledgeReadFailure,
    KnowledgeReadFailureKind,
    KnowledgeReadOutcome,
    KnowledgeReadResult,
    KnowledgeRecordIssue,
    KnowledgeRecordIssueKind,
)

NOW = "2026-10-24T12:00:00.000000Z"


def bundle(knowledge_id="k1", project="p1", evidence=True, provenance=True) -> KnowledgeBundle:
    capture = (
        CaptureKnowledgeProvenance(
            candidate_id="c1",
            project_id=project,
            category="decision",
            certainty="high",
            review_status="approved",
            candidate_verification_status="unverified",
            source_references=(),
            candidate_created_at=NOW,
            candidate_updated_at=NOW,
        )
        if provenance
        else None
    )
    record = KnowledgeRecord(
        knowledge_id, project, KnowledgeType.DECISION, "claim", NOW, NOW, capture_provenance=capture
    )
    items = (
        (
            EvidenceRecord(
                f"e-{knowledge_id}", project, EvidenceType.OTHER, "src", None, None, None, NOW,
                ReferenceStatus.AVAILABLE,
            ),
        )
        if evidence
        else ()
    )
    return KnowledgeBundle(record, items)


FAILURE = KnowledgeReadFailure(KnowledgeReadFailureKind.UNAVAILABLE, "source offline")


def test_success_with_records_defaults_to_unknown_coverage():
    result = KnowledgeReadResult.succeeded("p1", [bundle()])
    assert result.is_success and result.outcome is KnowledgeReadOutcome.SUCCEEDED
    assert result.coverage is KnowledgeCoverage.UNKNOWN
    assert len(result.records) == 1 and result.record_issues == ()
    assert not result.is_reported_complete


def test_empty_success_is_distinct_from_failure_and_scope_mismatch():
    empty = KnowledgeReadResult.succeeded("p1")
    failed = KnowledgeReadResult.failed("p1", FAILURE)
    mismatch = KnowledgeReadResult.scope_mismatch("p1")
    assert empty.is_success and empty.records == () and empty.failure is None
    assert empty.coverage is KnowledgeCoverage.UNKNOWN
    assert len({empty.outcome, failed.outcome, mismatch.outcome}) == 3
    assert empty != KnowledgeReadResult.failed("p1")
    assert not failed.is_success and failed.failure == FAILURE
    assert not mismatch.is_success and mismatch.records == ()


def test_failure_details_are_optional_for_non_success():
    assert KnowledgeReadResult.failed("p1").failure is None
    assert KnowledgeReadResult.scope_mismatch("p1").failure is None


def test_scope_mismatch_is_explicit_not_filtered():
    with pytest.raises(ValueError):
        KnowledgeReadResult.succeeded("p1", [bundle(project="other")])
    with pytest.raises(ValueError):
        KnowledgeReadResult.succeeded("p1", [bundle(), bundle("k2", project="other")])
    foreign_evidence = bundle()
    foreign_evidence = KnowledgeBundle(
        foreign_evidence.record, (dataclasses.replace(foreign_evidence.evidence[0], project="other"),)
    )
    with pytest.raises(ValueError):
        KnowledgeReadResult.succeeded("p1", [foreign_evidence])


def test_coverage_values_are_independent_of_outcome():
    partial = KnowledgeReadResult.succeeded(
        "p1", [bundle()], coverage=KnowledgeCoverage.PARTIAL, limitations=["page 2 unavailable"]
    )
    assert partial.is_success and partial.coverage is KnowledgeCoverage.PARTIAL
    assert partial.limitations == ("page 2 unavailable",)
    reported = KnowledgeReadResult.succeeded("p1", coverage=KnowledgeCoverage.REPORTED_COMPLETE)
    assert reported.is_reported_complete and reported.records == ()


def test_reported_complete_is_never_described_as_verified():
    assert "verified" not in {member.value for member in KnowledgeCoverage}
    reported = KnowledgeReadResult.succeeded(
        "p1", [bundle()], coverage=KnowledgeCoverage.REPORTED_COMPLETE, limitations=["note"]
    )
    assert reported.coverage.value == "reported_complete"
    assert REPORTED_COMPLETE_LIMITATION in reported.limitations
    assert "not independently verified" in REPORTED_COMPLETE_LIMITATION
    assert not hasattr(reported, "completeness_verified")
    assert reported.limitations.count(REPORTED_COMPLETE_LIMITATION) == 1
    again = dataclasses.replace(reported)
    assert again.limitations.count(REPORTED_COMPLETE_LIMITATION) == 1
    assert REPORTED_COMPLETE_LIMITATION not in KnowledgeReadResult.succeeded("p1").limitations


def test_record_issues_report_missing_evidence_and_provenance_without_fabricating():
    result = KnowledgeReadResult.succeeded(
        "p1", [bundle("a", evidence=False), bundle("b", provenance=False), bundle("c")]
    )
    assert {(i.knowledge_id, i.kind) for i in result.record_issues} == {
        ("a", KnowledgeRecordIssueKind.MISSING_EVIDENCE),
        ("b", KnowledgeRecordIssueKind.MISSING_CAPTURE_PROVENANCE),
    }
    assert result.records[0].evidence == () and result.records[1].record.capture_provenance is None
    assert result.outcome is KnowledgeReadOutcome.SUCCEEDED


def test_issues_do_not_change_outcome_or_coverage():
    result = KnowledgeReadResult.succeeded("p1", [bundle(evidence=False)], coverage=KnowledgeCoverage.PARTIAL)
    assert result.is_success and result.coverage is KnowledgeCoverage.PARTIAL and result.record_issues


def test_invalid_combinations_are_rejected():
    P = KnowledgeReadOutcome
    with pytest.raises(ValueError):
        KnowledgeReadResult("p1", P.SUCCEEDED, failure=FAILURE)
    for outcome in (P.FAILED, P.SCOPE_MISMATCH):
        with pytest.raises(ValueError):
            KnowledgeReadResult("p1", outcome, records=(bundle(),))
        with pytest.raises(ValueError):
            KnowledgeReadResult(
                "p1", outcome, record_issues=(KnowledgeRecordIssue("k1", KnowledgeRecordIssueKind.MISSING_EVIDENCE),)
            )
        for coverage in (KnowledgeCoverage.PARTIAL, KnowledgeCoverage.REPORTED_COMPLETE):
            with pytest.raises(ValueError):
                KnowledgeReadResult("p1", outcome, coverage=coverage)


def test_invalid_fields_are_rejected():
    with pytest.raises(ValueError):
        KnowledgeReadResult.succeeded("p1", [bundle(), bundle()])
    with pytest.raises(ValueError):
        KnowledgeReadResult(
            "p1",
            KnowledgeReadOutcome.SUCCEEDED,
            record_issues=(KnowledgeRecordIssue("ghost", KnowledgeRecordIssueKind.MISSING_EVIDENCE),),
        )
    for bad in ("", "  ", "a\x00b", None):
        with pytest.raises(ValueError):
            KnowledgeReadResult.succeeded(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        KnowledgeReadResult.succeeded("p1", limitations=[" "])
    with pytest.raises(ValueError):
        KnowledgeReadFailure(KnowledgeReadFailureKind.OTHER, "")
    with pytest.raises(TypeError):
        KnowledgeReadResult("p1", "succeeded")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        KnowledgeReadResult.succeeded("p1", ["not a bundle"])  # type: ignore[list-item]


def test_result_is_immutable_and_normalizes_to_tuples():
    result = KnowledgeReadResult.succeeded("p1", [bundle()], limitations=["x"])
    assert isinstance(result.records, tuple) and isinstance(result.limitations, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.coverage = KnowledgeCoverage.PARTIAL  # type: ignore[misc]
