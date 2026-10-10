"""Integration coverage using the production schema and synthetic records."""

import sqlite3

import pytest

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import service as service_module
from orbit.retrieval.fts import SearchIndexUnavailable
from orbit.retrieval.service import RetrievalService


def test_retrieval_service_searches_and_assembles_project_context(tmp_path):
    conn = connect(tmp_path / "retrieval.db")
    messages = ChatMessageRepository(conn)
    decisions = DecisionRepository(conn)

    source_message_id = messages.insert(
        "alpha", "conversation-1", "assistant", "SQLite stores the project data."
    )
    messages.insert("beta", "conversation-2", "user", "SQLite stores other data.")
    decisions.save(
        "alpha",
        "storage-choice",
        "Use SQLite as the project source of truth.",
        source_message_id=source_message_id,
        status="approved",
    )
    decisions.save("alpha", "proposal", "Try SQLite for a future cache.", status="draft")
    decisions.save("alpha", "old-choice", "SQLite was the previous source.", status="deprecated")

    service = RetrievalService(conn)
    search_results = service.search_chat_history("alpha", "SQLite", 10)
    assert len(search_results) == 1
    assert search_results[0].project_id == "alpha"
    assert search_results[0].source_id == "conversation-1"
    assert search_results[0].message_id == str(source_message_id)

    bundle = service.retrieve_context("alpha", "SQLite", 4_000)
    assert [item.record_kind for item in bundle.items][0] == "canonical_decision"
    assert bundle.items[0].status == "approved"
    assert all(item.status not in {"draft", "deprecated"} for item in bundle.items)
    assert bundle.items[0].relevance_score <= 0
    assert bundle.token_count_is_estimate is True
    assert bundle.token_count <= bundle.token_budget == 4_000
    assert all(item.project_id == "alpha" for item in bundle.items)
    message_item = next(item for item in bundle.items if item.record_kind == "chat_message")
    assert message_item.source_id == str(source_message_id)
    assert message_item.timestamp is not None
    conn.close()


def test_fts_indexes_follow_message_and_decision_updates(tmp_path):
    conn = connect(tmp_path / "fts-sync.db")
    messages = ChatMessageRepository(conn)
    decisions = DecisionRepository(conn)
    message_id = messages.insert("alpha", "conversation-1", "user", "oldterm")
    decisions.save("alpha", "choice", "oldterm", status="approved")
    conn.execute("UPDATE chat_messages SET content = 'newterm' WHERE id = ?", (message_id,))
    decisions.save("alpha", "choice", "newterm", status="approved")

    service = RetrievalService(conn)
    assert service.search_chat_history("alpha", "oldterm", 10) == []
    assert len(service.search_chat_history("alpha", "newterm", 10)) == 1
    bundle = service.retrieve_context("alpha", "newterm", 4_000)
    assert any(item.content == "newterm" for item in bundle.items)

    messages.delete(message_id)
    assert service.search_chat_history("alpha", "newterm", 10) == []
    conn.close()


def test_module_operations_return_mcp_friendly_traceable_dicts(tmp_path, monkeypatch):
    database_path = tmp_path / "public-api.db"
    real_connect = connect
    monkeypatch.setattr(
        service_module,
        "connect",
        lambda: real_connect(database_path),
    )
    with real_connect(database_path) as conn:
        messages = ChatMessageRepository(conn)
        decisions = DecisionRepository(conn)
        message_id = messages.insert(
            "alpha", "conversation-3", "assistant", "A traceable SQLite answer."
        )
        decisions.save(
            "alpha", "source-less", "SQLite decision without a source link.", status="approved"
        )

    results = service_module.search_chat_history("alpha", "traceable")
    assert len(results) == 1
    assert results[0]["message_id"] == str(message_id)
    assert results[0]["project"] == "alpha"
    assert results[0]["source_message_id"] == str(message_id)
    assert results[0]["conversation_id"] == "conversation-3"
    assert results[0]["role"] is None
    assert results[0]["content"] == "A traceable SQLite answer."
    assert isinstance(results[0]["score"], float)
    assert results[0]["created_at"]

    bundle = service_module.retrieve_context("alpha", "SQLite", token_budget=4_000)
    decision = next(item for item in bundle["items"] if item["record_kind"] == "canonical_decision")
    assert decision["record_id"].startswith("decision:")
    assert decision["source_message_id"] is None
    assert bundle["project"] == "alpha"
    assert bundle["query"] == "SQLite"
    assert bundle["token_count"] <= bundle["token_budget"] == 4_000


def test_unknown_project_and_empty_query_return_empty_results(tmp_path, monkeypatch):
    database_path = tmp_path / "empty-project.db"
    real_connect = connect
    monkeypatch.setattr(service_module, "connect", lambda: real_connect(database_path))

    assert service_module.search_chat_history("unknown", " ") == []
    assert service_module.search_chat_history("unknown", "not-present") == []
    bundle = service_module.retrieve_context("unknown", " ")
    assert bundle["items"] == []
    assert bundle["token_count"] == 0


def test_missing_fts_infrastructure_is_not_reported_as_empty_results():
    connection = sqlite3.connect(":memory:")
    service = RetrievalService(connection)

    with pytest.raises(SearchIndexUnavailable, match="missing or incompatible"):
        service.search_chat_history("alpha", "term")

    connection.close()


def test_database_errors_propagate_instead_of_becoming_empty_results(tmp_path):
    connection = connect(tmp_path / "closed.db")
    service = RetrievalService(connection)
    connection.close()

    with pytest.raises(sqlite3.ProgrammingError):
        service.search_chat_history("alpha", "term")
