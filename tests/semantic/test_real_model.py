"""Real embedding model check. Opt-in: needs the model (first run downloads ~130 MB).

    CELESTIN_RUN_MODEL_TESTS=1 python -m pytest tests/semantic/test_real_model.py
"""

import os

import pytest

pytest.importorskip("sqlite_vec")
pytest.importorskip("fastembed")

from orbit.mcp_server.persistence_services import PersistenceServices
from orbit.mcp_server.retrieval_services import RetrievalServices

pytestmark = pytest.mark.skipif(
    os.environ.get("CELESTIN_RUN_MODEL_TESTS") != "1", reason="set CELESTIN_RUN_MODEL_TESTS=1"
)


def test_real_model_finds_reworded_memory_and_keeps_exact_match(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    monkeypatch.setenv("CELESTIN_SEMANTIC_SEARCH", "1")
    monkeypatch.setenv("CELESTIN_DB_PATH", str(db))
    monkeypatch.delenv("CELESTIN_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("CELESTIN_VECTOR_DB_PATH", raising=False)
    persistence, retrieval = PersistenceServices(db), RetrievalServices(db)
    memory = persistence.ingest_chat_message(
        "demo", "c", "user", "We selected local persistence to avoid deployment overhead."
    )
    error = persistence.ingest_chat_message(
        "demo", "c", "user", "Checkout fails with ERR_PAYMENT_4471 on declined cards."
    )
    persistence.ingest_chat_message("other", "c", "user", "We selected local persistence to avoid deployment overhead.")

    result = retrieval.search_chat_history("demo", "Why did we avoid hosted infrastructure?", 5)
    assert result["retrieval"]["mode"] == "hybrid"
    assert result["results"][0]["message_id"] == memory["message_id"]
    assert {r["project"] for r in result["results"]} == {"demo"}
    exact = retrieval.search_chat_history("demo", "ERR_PAYMENT_4471", 5)
    assert exact["results"][0]["message_id"] == error["message_id"]
