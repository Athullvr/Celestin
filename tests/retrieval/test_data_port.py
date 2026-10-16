"""Behavioral contract checks for the retrieval data port's SQLite adapter."""

from types import SimpleNamespace

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval.sqlite_data import SQLiteRetrievalData
from orbit.semantic.search import SemanticUnavailable
from orbit.retrieval.service import RetrievalService
from orbit.retrieval.strategies import MESSAGE, DECISION, RetrievalRequest, SemanticStrategy


def test_sqlite_retrieval_data_preserves_search_ids_timestamps_and_tier(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        message_id = ChatMessageRepository(connection).insert(
            "alpha", "conversation", "user", "storage decision uses SQLite"
        )
        page = SQLiteRetrievalData(connection).search_messages(
            "alpha", "storage decision", 10, relax=True
        )

        assert len(page.matches) == 1
        hit = page.matches[0]
        assert hit.record_id == str(message_id)
        assert hit.project == "alpha"
        assert hit.source_id == "conversation"
        assert hit.timestamp
        assert page.tier == "strict"
    finally:
        connection.close()


def test_sqlite_retrieval_data_authoritative_loads_are_project_scoped(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        messages = ChatMessageRepository(connection)
        alpha_id = messages.insert("alpha", "a", "user", "alpha record")
        beta_id = messages.insert("beta", "b", "user", "beta record")
        decisions = DecisionRepository(connection)
        decisions.save("alpha", "policy", "approved alpha policy", alpha_id, "approved")
        decisions.save("beta", "policy", "beta secret", beta_id, "approved")
        adapter = SQLiteRetrievalData(connection)

        loaded_messages = adapter.load_messages("alpha", [str(alpha_id), str(beta_id)])
        loaded_decisions = adapter.load_decisions("alpha", ["1", "2"])

        assert list(loaded_messages) == [str(alpha_id)]
        assert loaded_messages[str(alpha_id)].created_at
        assert list(loaded_decisions) == ["1"]
        decision = loaded_decisions["1"]
        assert decision.status == "approved"
        assert decision.source_message_id == str(alpha_id)
        assert decision.updated_at
    finally:
        connection.close()


def test_sqlite_retrieval_data_uses_authoritative_decision_status_and_empty_results(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        message_id = ChatMessageRepository(connection).insert(
            "alpha", "conversation", "user", "decision record"
        )
        repository = DecisionRepository(connection)
        repository.save("alpha", "key", "decision record", message_id, "draft")
        adapter = SQLiteRetrievalData(connection)

        page = adapter.search_decisions("alpha", "decision record", 10, relax=True)
        empty = adapter.search_messages("missing", "decision record", 10, relax=True)

        assert len(page.matches) == 1
        assert page.matches[0].status == "draft"
        assert empty.matches == ()
        assert empty.tier == "strict"
    finally:
        connection.close()


def test_semantic_strategy_reloads_only_authoritative_project_records(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        messages = ChatMessageRepository(connection)
        alpha_id = messages.insert("alpha", "a", "user", "authoritative alpha message")
        beta_id = messages.insert("beta", "b", "user", "private beta message")
        alpha_decision = DecisionRepository(connection).save(
            "alpha", "choice", "authoritative alpha decision", alpha_id, "approved"
        )

        class Semantic:
            def search(self, project, query, *, kinds, limit):
                assert project == "alpha"
                return {
                    MESSAGE: [
                        SimpleNamespace(record_id=alpha_id, similarity=0.9),
                        SimpleNamespace(record_id=beta_id, similarity=0.8),
                        SimpleNamespace(record_id=9999, similarity=0.7),
                    ],
                    DECISION: [
                        SimpleNamespace(record_id=alpha_decision["id"], similarity=0.95),
                        SimpleNamespace(record_id=9998, similarity=0.6),
                    ],
                }

        strategy = SemanticStrategy(Semantic(), SQLiteRetrievalData(connection))
        result = strategy.retrieve(RetrievalRequest("alpha", "message", 10, 1000))

        assert result.stale == 3
        assert [candidate.content for candidate in result.candidates] == [
            "authoritative alpha message", "authoritative alpha decision"
        ]
        assert all(candidate.project == "alpha" for candidate in result.candidates)
        assert result.candidates[1].status == "approved"
    finally:
        connection.close()


def test_retrieval_service_accepts_injected_data_port(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        ChatMessageRepository(connection).insert(
            "alpha", "conversation", "user", "injected adapter record"
        )
        service = RetrievalService(retrieval_data=SQLiteRetrievalData(connection))

        result = service.search_chat_history("alpha", "injected", 10)

        assert len(result) == 1
        assert result[0].content == "injected adapter record"
    finally:
        connection.close()


def test_optional_semantic_failure_keeps_keyword_search_available(tmp_path):
    connection = connect(tmp_path / "retrieval.db")
    try:
        ChatMessageRepository(connection).insert(
            "alpha", "conversation", "user", "keyword fallback remains available"
        )

        class UnavailableSemantic:
            def search(self, *args, **kwargs):
                raise SemanticUnavailable("synthetic unavailable index")

        service = RetrievalService(connection, semantic=UnavailableSemantic())
        results = service.search_chat_history("alpha", "keyword fallback", 10)

        assert len(results) == 1
        assert results[0].content == "keyword fallback remains available"
        assert service.last_retrieval.mode == "fts_fallback"
    finally:
        connection.close()
