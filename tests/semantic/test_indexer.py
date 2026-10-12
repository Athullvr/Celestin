import pytest

pytest.importorskip("sqlite_vec")

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.semantic.indexer import Indexer
from orbit.semantic.vector_index import VectorIndex
from tests.semantic.fakes import FakeProvider


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "main.db")
    provider = FakeProvider()
    index = VectorIndex(tmp_path / "v.db", model_id=provider.model_id, dimension=provider.dimension)
    yield conn, provider, index
    index.close()
    conn.close()


def add_message(conn, content, project="p"):
    return ChatMessageRepository(conn).insert(project, "c", "user", content)


def add_decision(conn, key, value, source, status="draft", project="p"):
    repo = DecisionRepository(conn)
    repo.save(project=project, key=key, value=value, source_message_id=source, status="draft")
    if status != "draft":
        repo.update_status(project, key, status)


def test_sync_indexes_messages_and_only_approved_decisions(env):
    conn, provider, index = env
    m = add_message(conn, "local sqlite storage")
    add_decision(conn, "draft-key", "draft value storage", m)
    add_decision(conn, "ok-key", "approved value storage", m, "approved")
    add_decision(conn, "old-key", "old value storage", m, "deprecated")
    report = Indexer(conn, provider, index).sync()
    assert report.ok and report.embedded == 2
    assert index.count("chat_message") == 1 and index.count("canonical_decision") == 1


def test_sync_is_idempotent_and_skips_unchanged(env):
    conn, provider, index = env
    add_message(conn, "local sqlite storage")
    indexer = Indexer(conn, provider, index)
    indexer.sync()
    calls = len(provider.document_calls)
    report = indexer.sync()
    assert (report.embedded, report.unchanged) == (0, 1)
    assert len(provider.document_calls) == calls


def test_batches_are_used_and_everything_is_indexed(env):
    conn, provider, index = env
    for i in range(5):
        add_message(conn, f"hosted cloud message {i}")
    report = Indexer(conn, provider, index, batch_size=2).sync()
    assert report.embedded == 5 and index.count() == 5
    assert [len(c) for c in provider.document_calls] == [2, 2, 1]


def test_provider_outage_leaves_partial_index_and_rerun_resumes(env):
    conn, provider, index = env
    for i in range(4):
        add_message(conn, f"local storage {i}")
    indexer = Indexer(conn, provider, index, batch_size=2)
    original = provider.embed_documents
    state = {"n": 0}

    def flaky(texts):
        state["n"] += 1
        if state["n"] == 2:
            provider.fail = True
        return original(texts)

    provider.embed_documents = flaky
    report = indexer.sync()
    assert not report.ok and "re-run sync" in report.error
    assert index.count() == 2
    provider.fail = False
    provider.embed_documents = original
    report = indexer.sync()
    assert report.ok and report.embedded == 2 and index.count() == 4


def test_changed_status_deleted_and_edited_records_are_repaired(env):
    conn, provider, index = env
    m = add_message(conn, "local storage")
    gone = add_message(conn, "cloud hosted")
    add_decision(conn, "k", "database storage", m, "approved")
    indexer = Indexer(conn, provider, index)
    indexer.sync()
    assert index.count() == 3
    conn.execute("DELETE FROM chat_messages WHERE id = ?", (gone,))
    DecisionRepository(conn).update_status("p", "k", "deprecated")
    conn.execute("UPDATE chat_messages SET content = 'pasta recipe' WHERE id = ?", (m,))
    dry = indexer.sync(dry_run=True)
    assert (dry.embedded, dry.removed_stale) == (1, 2)
    assert index.count() == 3  # dry run changes nothing
    report = indexer.sync()
    assert (report.embedded, report.removed_stale) == (1, 2)
    assert index.count() == 1
    assert Indexer(conn, provider, index).sync().embedded == 0


def test_sync_never_modifies_sqlite(env):
    conn, provider, index = env
    add_message(conn, "local storage")
    before = conn.execute("SELECT COUNT(*), MAX(id) FROM chat_messages").fetchone()[:]
    Indexer(conn, provider, index).sync()
    assert conn.execute("SELECT COUNT(*), MAX(id) FROM chat_messages").fetchone()[:] == before


def test_index_record_adds_and_removes(env):
    conn, provider, index = env
    m = add_message(conn, "local storage")
    indexer = Indexer(conn, provider, index)
    indexer.index_record("chat_message", m)
    assert index.count() == 1
    conn.execute("DELETE FROM chat_messages WHERE id = ?", (m,))
    indexer.index_record("chat_message", m)
    assert index.count() == 0
