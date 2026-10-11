import pytest

pytest.importorskip("sqlite_vec")

from orbit.semantic.embeddings import EmbeddingError
from orbit.semantic.vector_index import VectorIndex, VectorIndexError, VectorRecord

DIM = 3


def open_index(path, **kw):
    return VectorIndex(path, model_id="m1", dimension=DIM, **kw)


def rec(kind, rid, project, vector, digest="h"):
    return VectorRecord(kind, rid, project, digest, vector)


def test_upsert_and_search_returns_stable_references(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 7, "p", [1, 0, 0]), rec("chat_message", 8, "p", [0, 1, 0])])
        hits = index.search([1, 0.1, 0], project="p", kind="chat_message", limit=5)
    assert [h.record_id for h in hits] == [7, 8]
    assert hits[0].kind == "chat_message" and hits[0].project == "p"
    assert hits[0].similarity > hits[1].similarity


def test_search_filters_project_and_kind_inside_the_query(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([
            rec("chat_message", 1, "a", [1, 0, 0]),
            rec("chat_message", 2, "b", [1, 0, 0]),
            rec("canonical_decision", 1, "a", [1, 0, 0]),
        ])
        hits = index.search([1, 0, 0], project="a", kind="chat_message", limit=1)
        assert [(h.project, h.kind, h.record_id) for h in hits] == [("a", "chat_message", 1)]
        assert index.search([1, 0, 0], project="zzz", kind="chat_message", limit=5) == []


def test_message_and_decision_ids_do_not_collide(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 5, "p", [1, 0, 0]), rec("canonical_decision", 5, "p", [0, 1, 0])])
        assert index.count("chat_message") == 1 and index.count("canonical_decision") == 1


def test_duplicate_upsert_is_idempotent_and_replaces(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 1, "p", [1, 0, 0], "old")])
        index.upsert([rec("chat_message", 1, "p", [0, 1, 0], "new")])
        assert index.count() == 1
        assert index.entries("chat_message", [1]) == {1: ("p", "new")}
        assert index.search([0, 1, 0], project="p", kind="chat_message", limit=1)[0].similarity == pytest.approx(1.0)
        assert index.health_check() == []


def test_delete_removes_vector_and_metadata(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 1, "p", [1, 0, 0])])
        index.delete("chat_message", 1)
        index.delete("chat_message", 99)  # missing record is not an error
        assert index.count() == 0
        assert index.search([1, 0, 0], project="p", kind="chat_message", limit=5) == []


def test_invalid_vectors_and_records_are_rejected_without_partial_writes(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        with pytest.raises(EmbeddingError):
            index.upsert([rec("chat_message", 1, "p", [1, 0, 0]), rec("chat_message", 2, "p", [1, 0])])
        with pytest.raises(VectorIndexError):
            index.upsert([rec("bogus", 1, "p", [1, 0, 0])])
        with pytest.raises(EmbeddingError):
            index.search([1, 0], project="p", kind="chat_message", limit=1)
        assert index.count() == 0


def test_missing_file_is_reported_not_created(tmp_path):
    with pytest.raises(VectorIndexError, match="celestin-index sync"):
        open_index(tmp_path / "missing.db", create=False)
    assert not (tmp_path / "missing.db").exists()


def test_model_or_dimension_change_requires_rebuild(tmp_path):
    path = tmp_path / "v.db"
    open_index(path).close()
    with pytest.raises(VectorIndexError, match="rebuild"):
        VectorIndex(path, model_id="other", dimension=DIM)
    with pytest.raises(VectorIndexError, match="rebuild"):
        VectorIndex(path, model_id="m1", dimension=4)
    with VectorIndex(path, model_id="other", dimension=4, check_compat=False) as index:
        index.reset()
    VectorIndex(path, model_id="other", dimension=4).close()


def test_health_check_detects_orphaned_metadata(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 1, "p", [1, 0, 0])])
        index._conn.execute("DELETE FROM vectors")
        assert index.health_check()


def test_reset_empties_the_index(tmp_path):
    with open_index(tmp_path / "v.db") as index:
        index.upsert([rec("chat_message", 1, "p", [1, 0, 0])])
        index.reset()
        assert index.count() == 0 and index.health_check(deep=True) == []
