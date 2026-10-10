"""Integration coverage using the production schema and synthetic records."""

from memory_bridge.database.engine import connect
from memory_bridge.repositories.decisions import DecisionRepository
from memory_bridge.repositories.messages import ChatMessageRepository
from memory_bridge.retrieval.service import RetrievalService


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
