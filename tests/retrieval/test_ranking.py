from __future__ import annotations

from dataclasses import replace

import pytest

from memory_bridge.retrieval import (
    RankingPolicy,
    RetrievalCandidate,
    SearchResult,
    rank_candidates,
)


def candidate(
    record_id,
    *,
    project_id="project-alpha",
    kind="chat_message",
    status=None,
    score=-1.0,
    timestamp="2026-01-01T00:00:00Z",
):
    return RetrievalCandidate(
        record_id=record_id,
        project_id=project_id,
        source_id=f"source-{record_id}",
        content=f"Content for {record_id}",
        timestamp=timestamp,
        relevance_score=score,
        record_kind=kind,
        status=status,
    )


def test_relevance_ranks_before_recency():
    older_stronger_match = candidate("older", score=-2.0, timestamp="2026-01-01T00:00:00Z")
    newer_weaker_match = candidate("newer", score=-1.0, timestamp="2026-01-09T00:00:00Z")

    results = rank_candidates(
        [newer_weaker_match, older_stronger_match],
        project_id="project-alpha",
    )

    assert [result.record_id for result in results] == ["older", "newer"]


def test_recency_breaks_equal_relevance_ties():
    older = candidate("older", timestamp="2026-01-01T00:00:00Z")
    newer = candidate("newer", timestamp="2026-01-09T00:00:00Z")

    results = rank_candidates([older, newer], project_id="project-alpha")

    assert [result.record_id for result in results] == ["newer", "older"]


def test_recency_tiebreak_can_be_disabled():
    older = candidate("a-older", timestamp="2026-01-01T00:00:00Z")
    newer = candidate("z-newer", timestamp="2026-01-09T00:00:00Z")

    results = rank_candidates(
        [newer, older],
        project_id="project-alpha",
        policy=RankingPolicy(recency_tiebreaker=False),
    )

    assert [result.record_id for result in results] == ["a-older", "z-newer"]


def test_approved_decision_priority_does_not_change_its_relevance_score():
    message = candidate("message", score=-100.0)
    approved = candidate(
        "decision-approved",
        kind="canonical_decision",
        status="approved",
        score=-0.1,
    )

    results = rank_candidates([message, approved], project_id="project-alpha")

    assert [result.record_id for result in results] == ["decision-approved", "message"]
    assert results[0].record_kind == "canonical_decision"
    assert results[0].status == "approved"
    assert results[0].relevance_score == -0.1


def test_drafts_and_deprecated_are_excluded_by_default():
    records = [
        candidate("approved", kind="canonical_decision", status="approved"),
        candidate("draft", kind="canonical_decision", status="draft"),
        candidate("deprecated", kind="canonical_decision", status="deprecated"),
    ]

    results = rank_candidates(records, project_id="project-alpha")

    assert [result.record_id for result in results] == ["approved"]


def test_explicit_status_overrides_keep_drafts_labeled_and_deprecated_last():
    records = [
        candidate("deprecated", kind="canonical_decision", status="deprecated"),
        candidate("draft", kind="canonical_decision", status="draft"),
        candidate("message"),
        candidate("approved", kind="canonical_decision", status="approved"),
    ]

    results = rank_candidates(
        records,
        project_id="project-alpha",
        policy=RankingPolicy(include_drafts=True, include_deprecated=True),
    )

    assert [result.record_id for result in results] == [
        "approved",
        "message",
        "draft",
        "deprecated",
    ]
    assert next(result for result in results if result.record_id == "draft").status == "draft"


def test_project_isolation_is_reapplied_during_ranking():
    records = [
        candidate("alpha", project_id="project-alpha"),
        candidate("beta", project_id="project-beta"),
    ]

    results = rank_candidates(records, project_id="project-alpha")

    assert [result.record_id for result in results] == ["alpha"]
    assert all(result.project_id == "project-alpha" for result in results)


def test_identical_inputs_produce_stable_ties():
    records = [candidate("record-z"), candidate("record-a"), candidate("record-m")]

    first = rank_candidates(records, project_id="project-alpha")
    second = rank_candidates(reversed(records), project_id="project-alpha")

    assert [result.record_id for result in first] == ["record-a", "record-m", "record-z"]
    assert second == first


def test_message_search_result_maps_without_losing_traceability():
    search_result = SearchResult(
        message_id="message-1",
        project_id="project-alpha",
        source_id="source-session-9",
        content="A matching message.",
        timestamp="2026-01-04T10:00:00Z",
        relevance_score=-0.7,
    )

    ranked = rank_candidates(
        [RetrievalCandidate.from_message_search_result(search_result)],
        project_id="project-alpha",
    )

    assert ranked == [
        RetrievalCandidate(
            record_id="message-1",
            project_id="project-alpha",
            source_id="source-session-9",
            content="A matching message.",
            timestamp="2026-01-04T10:00:00Z",
            relevance_score=-0.7,
            record_kind="chat_message",
        )
    ]


def test_missing_timestamps_rank_after_known_times_and_ties_stay_stable():
    missing_z = candidate("z-missing", timestamp=None)
    missing_a = candidate("a-missing", timestamp=None)
    known = candidate("known", timestamp="2026-01-01T00:00:00Z")

    results = rank_candidates(
        [missing_z, known, missing_a],
        project_id="project-alpha",
    )

    assert [result.record_id for result in results] == ["known", "a-missing", "z-missing"]


def test_missing_timestamp_is_preserved_from_fts_search_result():
    result = SearchResult(
        message_id="message-no-date",
        project_id="project-alpha",
        source_id="source-no-date",
        content="An undated message.",
        timestamp=None,
        relevance_score=-0.2,
    )

    candidate_result = RetrievalCandidate.from_message_search_result(result)

    assert candidate_result.timestamp is None
    assert rank_candidates([candidate_result], project_id="project-alpha") == [candidate_result]


@pytest.mark.parametrize(
    "source_ids",
    [(None, "some-id"), ("some-id", None)],
)
def test_nullable_source_id_tiebreak_is_type_safe(source_ids):
    base = candidate("same-record")
    records = [replace(base, source_id=source_id) for source_id in source_ids]

    results = rank_candidates(records, project_id="project-alpha")

    assert [result.source_id for result in results] == [None, "some-id"]
