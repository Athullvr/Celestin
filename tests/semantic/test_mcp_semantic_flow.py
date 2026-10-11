"""Vertical slice through the MCP adapters and the celestin-index CLI (fake embeddings)."""

import pytest

pytest.importorskip("sqlite_vec")

from orbit.mcp_server.persistence_services import PersistenceServices
from orbit.mcp_server.retrieval_services import RetrievalServices
from orbit.semantic import cli, config
from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from tests.semantic.fakes import FakeProvider


@pytest.fixture()
def semantic_env(tmp_path, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setenv("CELESTIN_SEMANTIC_SEARCH", "1")
    monkeypatch.setenv("CELESTIN_EMBEDDING_MODEL", provider.model_id)
    monkeypatch.setenv("CELESTIN_DB_PATH", str(tmp_path / "main.db"))
    monkeypatch.setenv("CELESTIN_VECTOR_DB_PATH", str(tmp_path / "v.db"))
    monkeypatch.setitem(config._providers, (provider.model_id, None), provider)
    monkeypatch.setattr("orbit.database.engine.DB_PATH", tmp_path / "main.db")
    return provider, tmp_path / "main.db"


def test_ingest_index_search_with_different_wording_and_context(semantic_env):
    provider, db = semantic_env
    persistence, retrieval = PersistenceServices(db), RetrievalServices(db)
    saved = persistence.ingest_chat_message(
        "demo", "c1", "user", "We selected local persistence to avoid deployment overhead."
    )
    persistence.ingest_chat_message("other", "c1", "user", "local persistence deployment overhead")
    result = retrieval.search_chat_history("demo", "why did we avoid hosted infrastructure", 10)
    assert [r["message_id"] for r in result["results"]] == [saved["message_id"]]
    assert result["retrieval"] == {"mode": "hybrid", "warnings": []}
    context = retrieval.retrieve_context("demo", "why did we avoid hosted infrastructure", 2000)
    assert [i["record_id"] for i in context["items"]] == [saved["message_id"]]
    assert context["items"][0]["source_message_id"] == saved["message_id"]
    assert context["retrieval"]["mode"] == "hybrid"


def test_write_succeeds_and_is_repairable_when_embedding_is_down(semantic_env):
    provider, db = semantic_env
    provider.fail = True
    saved = PersistenceServices(db).ingest_chat_message("demo", "c1", "user", "hosted cloud server")
    assert saved["message_id"]  # SQLite write is not blocked by the index
    retrieval = RetrievalServices(db)
    result = retrieval.search_chat_history("demo", "hosted", 10)
    assert result["retrieval"]["mode"] == "fts_fallback" and len(result["results"]) == 1
    provider.fail = False
    assert cli.main(["sync"]) == 0
    assert retrieval.search_chat_history("demo", "hosted", 10)["retrieval"]["mode"] == "hybrid"


def test_response_schema_unchanged_when_semantic_disabled(semantic_env, monkeypatch):
    _, db = semantic_env
    monkeypatch.delenv("CELESTIN_SEMANTIC_SEARCH")
    PersistenceServices(db).ingest_chat_message("demo", "c1", "user", "hosted cloud")
    assert "retrieval" not in RetrievalServices(db).search_chat_history("demo", "hosted", 10)
    assert "retrieval" not in RetrievalServices(db).retrieve_context("demo", "hosted", 100)


def test_cli_sync_status_and_rebuild(semantic_env, capsys):
    provider, db = semantic_env
    conn = connect(db)
    from orbit.repositories.messages import ChatMessageRepository
    mid = ChatMessageRepository(conn).insert("demo", "c", "user", "local sqlite storage")
    repo = DecisionRepository(conn)
    repo.save(project="demo", key="k", value="database storage", source_message_id=mid, status="draft")
    repo.update_status("demo", "k", "approved")
    conn.close()
    assert cli.main(["status"]) == 1  # no index yet
    assert cli.main(["sync"]) == 0
    assert "embedded=2" in capsys.readouterr().out
    assert cli.main(["status"]) == 0
    assert cli.main(["sync"]) == 0 and "embedded=0" in capsys.readouterr().out
    assert cli.main(["rebuild"]) == 0 and "embedded=2" in capsys.readouterr().out


def test_cli_rebuild_recovers_from_a_corrupt_index_file(semantic_env, tmp_path, capsys):
    provider, db = semantic_env
    PersistenceServices(db).ingest_chat_message("demo", "c", "user", "local storage")
    (tmp_path / "v.db").write_bytes(b"garbage" * 500)
    assert cli.main(["sync"]) == 1
    assert cli.main(["rebuild"]) == 0
    assert cli.main(["status"]) == 0


def test_cli_reports_provider_outage(semantic_env, capsys):
    provider, db = semantic_env
    provider.fail = True
    PersistenceServices(db).ingest_chat_message("demo", "c", "user", "local storage")
    assert cli.main(["sync"]) == 1
    assert "re-run sync" in capsys.readouterr().err
