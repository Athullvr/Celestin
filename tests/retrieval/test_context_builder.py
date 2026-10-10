from __future__ import annotations

import json

import pytest

from memory_bridge.retrieval import (
    DEFAULT_TOKEN_BUDGET,
    RankingPolicy,
    RetrievalCandidate,
    Utf8ByteTokenEstimator,
    build_context_bundle,
)


def candidate(
    record_id,
    content,
    *,
    kind="chat_message",
    status=None,
    score=-1.0,
    timestamp="2026-01-01T00:00:00Z",
    source_id=None,
):
    return RetrievalCandidate(
        record_id=record_id,
        project_id="project-alpha",
        source_id=source_id or f"source-{record_id}",
        content=content,
        timestamp=timestamp,
        relevance_score=score,
        record_kind=kind,
        status=status,
    )


def test_empty_candidates_return_empty_bundle():
    bundle = build_context_bundle([], project_id="project-alpha")

    assert bundle.project_id == "project-alpha"
    assert bundle.items == ()
    assert bundle.excluded == ()
    assert bundle.rendered_context == ""
    assert bundle.token_count == 0
    assert bundle.token_budget == DEFAULT_TOKEN_BUDGET == 2_000
    assert bundle.token_count_is_estimate is True


def test_single_record_over_budget_is_excluded_without_truncation():
    record = candidate("long", "This complete record must remain intact.")
    bundle = build_context_bundle([record], project_id="project-alpha", token_budget=10)

    assert bundle.items == ()
    assert bundle.rendered_context == ""
    assert bundle.token_count == 0
    assert bundle.excluded[0].record_id == "long"
    assert bundle.excluded[0].source_id == "source-long"
    assert bundle.excluded[0].reason == "token_budget"


def test_multiple_records_fit_at_exact_budget_boundary():
    records = [candidate("first", "First complete record."), candidate("second", "Second complete record.")]
    estimator = Utf8ByteTokenEstimator()
    unbounded = build_context_bundle(records, project_id="project-alpha", token_budget=10_000)
    exact_budget = unbounded.token_count

    bundle = build_context_bundle(
        records,
        project_id="project-alpha",
        token_budget=exact_budget,
        token_counter=estimator,
    )

    assert [item.record_id for item in bundle.items] == ["first", "second"]
    assert bundle.token_count == exact_budget
    assert bundle.token_count == estimator.count_tokens(bundle.rendered_context)


def test_approved_decision_is_selected_before_message():
    approved = candidate(
        "decision",
        "Use SQLite for canonical state.",
        kind="canonical_decision",
        status="approved",
        score=-0.1,
    )
    message = candidate("message", "A historical discussion about SQLite.", score=-100.0)
    single_decision_budget = build_context_bundle(
        [approved],
        project_id="project-alpha",
        token_budget=10_000,
    ).token_count

    bundle = build_context_bundle(
        [message, approved],
        project_id="project-alpha",
        token_budget=single_decision_budget,
    )

    assert [item.record_id for item in bundle.items] == ["decision"]
    assert bundle.excluded[0].record_id == "message"
    assert bundle.excluded[0].reason == "token_budget"


def test_traceability_metadata_is_preserved_in_items_and_rendered_context():
    record = candidate(
        "message-7",
        "The recorded content.",
        timestamp="2026-04-05T06:07:08Z",
        source_id="chat-source-7",
    )

    bundle = build_context_bundle([record], project_id="project-alpha")
    rendered = json.loads(bundle.rendered_context)
    item = bundle.items[0]

    assert item.record_id == rendered["record_id"] == "message-7"
    assert item.source_id == rendered["source_id"] == "chat-source-7"
    assert item.project_id == rendered["project_id"] == "project-alpha"
    assert item.timestamp == rendered["timestamp"] == "2026-04-05T06:07:08Z"
    assert item.record_kind == rendered["record_kind"] == "chat_message"
    assert item.content == rendered["content"] == "The recorded content."


def test_duplicate_content_is_included_once_and_exclusion_is_traceable():
    approved = candidate(
        "decision",
        "Use   SQLite for canonical state.",
        kind="canonical_decision",
        status="approved",
    )
    historical_duplicate = candidate("message", "use SQLite for canonical state.")

    bundle = build_context_bundle(
        [historical_duplicate, approved],
        project_id="project-alpha",
    )

    assert [item.record_id for item in bundle.items] == ["decision"]
    assert bundle.excluded[0].record_id == "message"
    assert bundle.excluded[0].source_id == "source-message"
    assert bundle.excluded[0].reason == "duplicate_content"


def test_oversized_candidate_is_skipped_so_later_small_record_can_fit():
    long_record = candidate("long", "x" * 800)
    short_record = candidate("short", "Tiny.")
    short_budget = build_context_bundle(
        [short_record],
        project_id="project-alpha",
    ).token_count

    bundle = build_context_bundle(
        [long_record, short_record],
        project_id="project-alpha",
        token_budget=short_budget,
    )

    assert [item.record_id for item in bundle.items] == ["short"]
    assert bundle.excluded[0].record_id == "long"
    assert bundle.excluded[0].reason == "token_budget"


def test_nonpositive_token_budget_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        build_context_bundle([], project_id="project-alpha", token_budget=0)


def test_draft_and_deprecated_records_obey_ranking_status_policy():
    records = [
        candidate("draft", "Possible future direction.", kind="canonical_decision", status="draft"),
        candidate("deprecated", "Old direction.", kind="canonical_decision", status="deprecated"),
        candidate("approved", "Current direction.", kind="canonical_decision", status="approved"),
    ]

    defaults = build_context_bundle(records, project_id="project-alpha")
    overrides = build_context_bundle(
        records,
        project_id="project-alpha",
        ranking_policy=RankingPolicy(include_drafts=True, include_deprecated=True),
    )

    assert [item.record_id for item in defaults.items] == ["approved"]
    assert [item.record_id for item in overrides.items] == ["approved", "draft", "deprecated"]
    assert next(item for item in overrides.items if item.record_id == "draft").status == "draft"
