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


@pytest.mark.parametrize("query", ["(((***+++)))", "!!!???---", "😀🔥"])
def test_punctuation_heavy_queries_return_no_results(searcher, query):
    assert searcher.search(query, project_id="project-alpha") == []


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


def test_project_filter_value_cannot_expand_to_other_projects(searcher):
    results = searcher.search("local cache", project_id="' OR 1=1 --")

    assert results == []


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


def test_existing_empty_fts_table_returns_no_results(tmp_path):
    connection = sqlite3.connect(tmp_path / "empty-index.sqlite3")
    connection.execute("CREATE VIRTUAL TABLE messages USING fts5(message_id UNINDEXED, project_id UNINDEXED, source_id UNINDEXED, created_at UNINDEXED, content)")
    search = FtsMessageSearch(
        connection,
        FtsSchema("messages", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    assert search.search("anything", project_id="project-alpha") == []

    connection.close()


def test_non_fts_table_with_compatible_columns_is_reported_incompatible(tmp_path):
    connection = sqlite3.connect(tmp_path / "not-fts.sqlite3")
    connection.execute(
        "CREATE TABLE messages (message_id TEXT, project_id TEXT, source_id TEXT, created_at TEXT, content TEXT)"
    )
    search = FtsMessageSearch(
        connection,
        FtsSchema("messages", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    with pytest.raises(SearchIndexUnavailable, match="missing or incompatible"):
        search.search("anything", project_id="project-alpha")

    connection.close()


def test_fts_table_with_missing_configured_content_column_is_reported(tmp_path):
    connection = sqlite3.connect(tmp_path / "wrong-column.sqlite3")
    connection.execute("CREATE VIRTUAL TABLE messages USING fts5(body)")
    search = FtsMessageSearch(
        connection,
        FtsSchema("messages", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    with pytest.raises(SearchIndexUnavailable, match="missing or incompatible"):
        search.search("anything", project_id="project-alpha")

    connection.close()


def test_unicode_content_is_searchable_with_traceable_result(tmp_path):
    connection = sqlite3.connect(tmp_path / "unicode.sqlite3")
    connection.execute("CREATE VIRTUAL TABLE messages USING fts5(message_id UNINDEXED, project_id UNINDEXED, source_id UNINDEXED, created_at UNINDEXED, content)")
    connection.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
        ("unicode-1", "project-alpha", "source-unicode", "2026-02-01T00:00:00Z", "naïve café 東京"),
    )
    search = FtsMessageSearch(
        connection,
        FtsSchema("messages", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    results = search.search("café", project_id="project-alpha")

    assert len(results) == 1
    assert results[0].message_id == "unicode-1"
    assert results[0].source_id == "source-unicode"
    assert results[0].timestamp == "2026-02-01T00:00:00Z"
    assert results[0].content == "naïve café 東京"

    connection.close()


def test_equal_or_missing_timestamps_have_stable_database_order(tmp_path):
    connection = sqlite3.connect(tmp_path / "timestamp-ties.sqlite3")
    connection.execute("CREATE VIRTUAL TABLE messages USING fts5(message_id UNINDEXED, project_id UNINDEXED, source_id UNINDEXED, created_at UNINDEXED, content)")
    connection.executemany(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
        [
            ("null-z", "project-alpha", "source-z", None, "same searchable phrase"),
            ("equal-b", "project-alpha", "source-b", "2026-02-01T00:00:00Z", "same searchable phrase"),
            ("null-a", "project-alpha", "source-a", None, "same searchable phrase"),
            ("equal-a", "project-alpha", "source-a", "2026-02-01T00:00:00Z", "same searchable phrase"),
        ],
    )
    search = FtsMessageSearch(
        connection,
        FtsSchema("messages", "message_id", "project_id", "source_id", "created_at", "content"),
    )

    first = search.search("searchable phrase", project_id="project-alpha")
    second = search.search("searchable phrase", project_id="project-alpha")

    assert [result.message_id for result in first] == ["equal-a", "equal-b", "null-a", "null-z"]
    assert [result.message_id for result in second] == [result.message_id for result in first]
    assert [result.timestamp for result in first] == [
        "2026-02-01T00:00:00Z",
        "2026-02-01T00:00:00Z",
        None,
        None,
    ]

    connection.close()


def test_malformed_identifier_is_rejected():
    with pytest.raises(ValueError, match="Invalid SQLite identifier"):
        FtsSchema("messages; DROP TABLE x", "message_id", "project_id", "source_id", "created_at", "content")
