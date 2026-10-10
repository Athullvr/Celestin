from __future__ import annotations

import sqlite3

import pytest

from fixtures import MESSAGES
from memory_bridge.retrieval import FtsMessageSearch, FtsSchema, SearchIndexUnavailable


@pytest.fixture
def searcher(tmp_path):
    database_path = tmp_path / "retrieval.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """CREATE VIRTUAL TABLE retrieval_messages_fts USING fts5(
            message_id UNINDEXED,
            project_id UNINDEXED,
            source_id UNINDEXED,
            created_at UNINDEXED,
            content
        )"""
    )
    connection.executemany(
        """INSERT INTO retrieval_messages_fts
           (message_id, project_id, source_id, created_at, content)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                row["fixture_record_id"],
                row["fixture_project_id"],
                row["fixture_source_id"],
                row["fixture_created_at"],
                row["fixture_text"],
            )
            for row in MESSAGES
        ],
    )
    connection.executemany(
        """INSERT INTO retrieval_messages_fts
           (message_id, project_id, source_id, created_at, content)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                "message-alpha-2",
                "project-alpha",
                "source-session-6",
                "2026-01-07T10:00:00Z",
                "A local cache makes alpha lookups faster.",
            ),
            (
                "message-alpha-3",
                "project-alpha",
                "source-session-7",
                "2026-01-08T10:00:00Z",
                "Alpha has a cache for repeated reads.",
            ),
        ],
    )
    schema = FtsSchema(
        table="retrieval_messages_fts",
        message_id="message_id",
        project_id="project_id",
        source_id="source_id",
        created_at="created_at",
        content="content",
    )
    yield FtsMessageSearch(connection, schema)
    connection.close()


def test_search_returns_multiple_matching_messages(searcher):
    results = searcher.search("local cache", project_id="project-alpha")

    assert {result.message_id for result in results} == {
        "message-alpha-1",
        "message-alpha-2",
    }
    assert results[0].relevance_score <= results[1].relevance_score


@pytest.mark.parametrize("query", ["", "   ", "--- !!!"])
def test_empty_or_non_word_query_returns_no_results(searcher, query):
    assert searcher.search(query, project_id="project-alpha") == []


def test_no_match_returns_empty_list(searcher):
    assert searcher.search("unrelatedterm", project_id="project-alpha") == []


def test_special_characters_are_treated_as_plain_query_text(searcher):
    results = searcher.search("cache!!!", project_id="project-alpha")

    assert results
    assert all("cache" in result.content.lower() for result in results)


def test_results_preserve_source_ids_timestamps_and_project(searcher):
    results = searcher.search("local cache", project_id="project-alpha")
    first_result = next(result for result in results if result.message_id == "message-alpha-1")

    assert first_result.project_id == "project-alpha"
    assert first_result.source_id == "source-session-1"
    assert first_result.timestamp == "2026-01-02T10:00:00Z"
    assert first_result.content == "The alpha service uses a local cache."
    assert isinstance(first_result.relevance_score, float)


def test_search_is_scoped_to_the_requested_project(searcher):
    results = searcher.search("local cache", project_id="project-beta")

    assert [result.message_id for result in results] == ["message-beta-1"]
    assert all(result.project_id == "project-beta" for result in results)


@pytest.mark.parametrize(
    ("query", "project_id", "limit", "error"),
    [
        (None, "project-alpha", 10, TypeError),
        ("cache", " ", 10, ValueError),
        ("cache", "project-alpha", 0, ValueError),
        ("cache", "project-alpha", True, TypeError),
        ("bad\x00query", "project-alpha", 10, ValueError),
    ],
)
def test_invalid_inputs_have_clear_errors(searcher, query, project_id, limit, error):
    with pytest.raises(error):
        searcher.search(query, project_id=project_id, limit=limit)


def test_missing_fts_table_raises_clear_error(tmp_path):
    connection = sqlite3.connect(tmp_path / "empty.sqlite3")
    search = FtsMessageSearch(
        connection,
        FtsSchema("missing_fts", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    with pytest.raises(SearchIndexUnavailable, match="missing or incompatible"):
        search.search("cache", project_id="project-alpha")

    connection.close()


def test_malformed_identifier_is_rejected():
    with pytest.raises(ValueError, match="Invalid SQLite identifier"):
        FtsSchema("messages; DROP TABLE x", "message_id", "project_id", "source_id", "created_at", "content")
