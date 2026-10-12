import pytest

pytest.importorskip("sqlite_vec")

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService, reciprocal_rank_fusion
from orbit.semantic.indexer import Indexer
from orbit.semantic.search import SemanticSearch
from orbit.semantic.vector_index import VectorIndex
from tests.semantic.fakes import FakeProvider


class Env:
    def __init__(self, tmp_path, min_similarity=0.5):
        self.conn = connect(tmp_path / "main.db")
        self.provider = FakeProvider()
        self.vpath = tmp_path / "v.db"
        self.messages = ChatMessageRepository(self.conn)
        self.decisions = DecisionRepository(self.conn)
        self.min_similarity = min_similarity

    def message(self, content, project="p"):
        return self.messages.insert(project, "conv", "user", content)

    def decision(self, key, value, source, status, project="p"):
        self.decisions.save(project=project, key=key, value=value, source_message_id=source, status="draft")
        if status != "draft":
            self.decisions.update_status(project, key, status)

    def sync(self):
        with VectorIndex(self.vpath, model_id=self.provider.model_id, dimension=self.provider.dimension) as index:
            return Indexer(self.conn, self.provider, index).sync()

    def service(self, semantic=True):
        search = SemanticSearch(self.provider, self.vpath, self.min_similarity) if semantic else None
        return RetrievalService(self.conn, semantic=search)


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


def ids(results):
    return [r.message_id for r in results]


def test_rrf_is_deterministic_deduplicated_and_rank_based():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4]], k=60)
    assert [i for i, _ in fused] == [3, 1, 2, 4]  # 3 is in both lists; 2 and 4 tie on score, lower id first
    assert dict(fused)[3] == pytest.approx(1 / 63 + 1 / 61)
    assert reciprocal_rank_fusion([[1, 1, 1]]) == [(1, pytest.approx(1 / 61))]
    assert reciprocal_rank_fusion([]) == []


def test_fts_only_match_keeps_exact_identifier_retrieval(env):
    exact = env.message("error E4711 raised by the cache layer")
    env.message("local sqlite storage")
    env.sync()
    assert ids(env.service().search_chat_history("p", "E4711"))[0] == str(exact)


def test_semantic_only_match_uses_different_wording(env):
    target = env.message("We selected local persistence to avoid deployment overhead.")
    env.message("pasta recipe with tomato")
    env.sync()
    query = "why avoid hosted infrastructure"  # no shared FTS terms with the message
    assert env.service(semantic=False).search_chat_history("p", query) == []
    results = env.service().search_chat_history("p", query)
    assert ids(results) == [str(target)]
    assert results[0].project_id == "p" and results[0].source_id == "conv"


def test_record_found_by_both_paths_is_not_duplicated_and_ranks_first(env):
    both = env.message("hosted deployment overhead is costly")
    only_semantic = env.message("cloud infrastructure server")
    env.message("pasta recipe")
    env.sync()
    service = env.service()
    results = service.search_chat_history("p", "hosted deployment infrastructure")
    assert ids(results).count(str(both)) == 1
    assert ids(results)[0] == str(both)
    assert str(only_semantic) in ids(results)
    assert service.last_retrieval.mode == "hybrid"


def test_hybrid_ordering_is_deterministic(env):
    for _ in range(3):
        env.message("cloud hosted server")
    env.sync()
    first = ids(env.service().search_chat_history("p", "infrastructure"))
    assert first == ids(env.service().search_chat_history("p", "infrastructure"))


def test_project_isolation_in_vector_and_fts_paths(env):
    env.message("cloud hosted infrastructure", project="other")
    mine = env.message("deployment overhead cloud", project="p")
    env.sync()
    results = env.service().search_chat_history("p", "hosted infrastructure")
    assert ids(results) == [str(mine)] and {r.project_id for r in results} == {"p"}
    assert env.service().search_chat_history("nobody", "hosted infrastructure") == []
    bundle = env.service().retrieve_context("p", "hosted infrastructure", 2000)
    assert all(item.project_id == "p" for item in bundle.items)


def test_stale_vector_hit_for_a_row_moved_to_another_project_is_discarded(env):
    moved = env.message("deployment cloud", project="p")
    env.sync()
    env.conn.execute("UPDATE chat_messages SET project = 'other' WHERE id = ?", (moved,))  # index now stale
    service = env.service()
    assert service.search_chat_history("p", "hosted infrastructure") == []
    assert any("no matching SQLite record" in w for w in service.last_retrieval.warnings)
    assert all(i.project_id == "p" for i in service.retrieve_context("p", "hosted infrastructure", 2000).items)


def test_decision_status_policy_is_preserved(env):
    src = env.message("storage background")
    env.decision("approved-key", "local database storage approved", src, "approved")
    env.decision("draft-key", "local database storage draft", src, "draft")
    env.decision("old-key", "local database storage old", src, "deprecated")
    env.sync()
    bundle = env.service().retrieve_context("p", "persistence sqlite", 5000)
    decisions = [i for i in bundle.items if i.record_kind == "canonical_decision"]
    assert [d.status for d in decisions] == ["approved"]
    assert "draft" not in bundle.rendered_context and "old" not in bundle.rendered_context.split()
    assert bundle.items[0].record_kind == "canonical_decision"  # approved decisions first


def test_decision_edited_to_draft_after_indexing_is_filtered(env):
    src = env.message("storage background")
    env.decision("k", "local database storage", src, "approved")
    env.sync()
    DecisionRepository(env.conn).update_status("p", "k", "draft")  # index is now stale
    bundle = env.service().retrieve_context("p", "persistence sqlite", 5000)
    assert not [i for i in bundle.items if i.record_kind == "canonical_decision"]


def test_provenance_is_preserved_for_semantic_decisions(env):
    src = env.message("cloud background")
    env.decision("k", "local database storage", src, "approved")
    env.sync()
    bundle = env.service().retrieve_context("p", "persistence sqlite", 5000)
    item = next(i for i in bundle.items if i.record_kind == "canonical_decision")
    assert item.source_id == str(src) and item.record_id.startswith("decision:")


def test_budget_still_enforced_with_hybrid(env):
    for i in range(10):
        env.message(f"cloud hosted deployment note {i} " + "x" * 200)
    env.sync()
    bundle = env.service().retrieve_context("p", "infrastructure", 600)
    assert bundle.token_count <= 600 and bundle.excluded


@pytest.mark.parametrize("query", ["", "   ", "!!!"])
def test_empty_or_punctuation_queries_return_nothing(env, query):
    env.message("cloud hosted")
    env.sync()
    service = env.service()
    assert service.search_chat_history("p", query) == []
    assert service.last_retrieval.mode == "hybrid"


def test_similarity_threshold_blocks_unrelated_neighbours(env):
    env.message("pasta recipe tomato")
    env.sync()
    assert env.service().search_chat_history("p", "login password") == []


def test_semantic_disabled_reports_fts_mode(env):
    env.message("hosted cloud")
    service = env.service(semantic=False)
    assert len(service.search_chat_history("p", "hosted")) == 1
    assert service.last_retrieval.mode == "fts" and not service.semantic_enabled


# ---- failure modes -------------------------------------------------------

def test_embedding_outage_falls_back_to_fts_with_warning(env):
    target = env.message("hosted cloud server")
    env.sync()
    env.provider.fail = True
    service = env.service()
    assert ids(service.search_chat_history("p", "hosted")) == [str(target)]
    assert service.last_retrieval.mode == "fts_fallback"
    assert "fake provider outage" in service.last_retrieval.warnings[0]
    bundle = service.retrieve_context("p", "hosted", 2000)
    assert [i.record_id for i in bundle.items] == [str(target)]
    assert service.last_retrieval.mode == "fts_fallback"


def test_missing_vector_index_falls_back_and_points_to_sync(env):
    target = env.message("hosted cloud server")
    service = env.service()  # never synced: no vector file
    assert ids(service.search_chat_history("p", "hosted")) == [str(target)]
    assert service.last_retrieval.mode == "fts_fallback"
    assert "celestin-index sync" in service.last_retrieval.warnings[0]
    assert not env.vpath.exists()


def test_corrupt_vector_index_falls_back(env):
    env.message("hosted cloud server")
    env.vpath.write_bytes(b"this is not a sqlite database" * 100)
    service = env.service()
    assert len(service.search_chat_history("p", "hosted")) == 1
    assert service.last_retrieval.mode == "fts_fallback"


def test_inconsistent_index_reports_rebuild(env):
    env.message("hosted cloud server")
    env.sync()
    with VectorIndex(env.vpath, model_id=env.provider.model_id, dimension=env.provider.dimension) as index:
        index._conn.execute("DELETE FROM vectors")
    service = env.service()
    assert len(service.search_chat_history("p", "hosted")) == 1
    assert service.last_retrieval.mode == "fts_fallback"
    assert "celestin-index rebuild" in service.last_retrieval.warnings[0]


def test_model_change_reports_rebuild_then_rebuild_recovers(env):
    target = env.message("deployment cloud")
    env.sync()
    env.provider.model_id = "another-model"
    service = env.service()
    assert service.search_chat_history("p", "hosted infrastructure") == []
    assert service.last_retrieval.mode == "fts_fallback"
    with VectorIndex(env.vpath, model_id="another-model", dimension=env.provider.dimension,
                     check_compat=False) as index:
        index.reset()
        Indexer(env.conn, env.provider, index).sync()
    service = env.service()
    assert ids(service.search_chat_history("p", "hosted infrastructure")) == [str(target)]
    assert service.last_retrieval.mode == "hybrid"


def test_unavailable_provider_object_reports_reason(env):
    target = env.message("hosted cloud")
    service = RetrievalService(env.conn, semantic=SemanticSearch.unavailable("fastembed is not installed"))
    assert ids(service.search_chat_history("p", "hosted")) == [str(target)]
    assert "fastembed is not installed" in service.last_retrieval.warnings[0]


def test_relative_margin_drops_weak_neighbours(tmp_path):
    env = Env(tmp_path, min_similarity=0.1)
    strong = env.message("hosted cloud server deployment")
    weak = env.message("hosted pasta recipe tomato")
    env.sync()
    query = "hosted cloud server deployment"
    assert set(ids(env.service().search_chat_history("p", query))) == {str(strong), str(weak)}
    narrow = RetrievalService(env.conn, semantic=SemanticSearch(env.provider, env.vpath, 0.1, relative_margin=0.2))
    assert ids(narrow.search_chat_history("p", query)) == [str(strong)]
