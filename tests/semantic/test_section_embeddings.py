import pytest

pytest.importorskip("sqlite_vec")
pytest.importorskip("pageindex")

from orbit.database.engine import connect
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.store import PageIndexStore
from orbit.retrieval import RetrievalService
from orbit.semantic.indexer import Indexer
from orbit.semantic.search import SemanticSearch
from orbit.semantic.vector_index import VectorIndex
from tests.semantic.fakes import FakeProvider

MD = ("# Storage\n\n## Persistence\n\nWe selected local sqlite persistence to keep deployment simple.\n\n"
      "## Cooking\n\nPasta recipe with tomato.\n")


@pytest.fixture()
def env(tmp_path):
    class E:
        pass

    e = E()
    e.conn = connect(tmp_path / "m.db")
    e.provider = FakeProvider()
    e.vpath, e.docs = tmp_path / "v.db", tmp_path / "docs.db"
    with PageIndexStore(e.docs) as store:
        index_markdown_text(store, "p", "a.md", MD)
        index_markdown_text(store, "q", "a.md", MD)

    def sync(dry_run=False):
        with PageIndexStore(e.docs, create=False) as store, VectorIndex(
                e.vpath, model_id=e.provider.model_id, dimension=e.provider.dimension) as index:
            return Indexer(e.conn, e.provider, index, sections_connection=store.connection()).sync(dry_run=dry_run), index.count("document_section")

    e.sync = sync
    e.service = lambda: RetrievalService(e.conn, semantic=SemanticSearch(e.provider, e.vpath, 0.1), sections=e.docs)
    return e


def test_sections_are_embedded_idempotently_and_found_with_different_wording(env):
    report, count = env.sync()
    assert report.ok and count == 6  # 3 sections x 2 projects
    assert env.sync()[0].embedded == 0
    service = env.service()
    bundle = service.retrieve_context("p", "why avoid hosted cloud infrastructure", 5000)  # no FTS overlap
    items = [i for i in bundle.items if i.record_kind == "document_section"]
    assert items and "persistence" in items[0].content.lower() and all(i.project_id == "p" for i in items)
    assert service.last_retrieval.sections == "used"


def test_replaced_documents_get_new_embeddings_and_stale_ones_are_removed(env):
    env.sync()
    with PageIndexStore(env.docs) as store:
        index_markdown_text(store, "p", "a.md", "# Storage\n\n## Persistence\n\nlocal sqlite persistence changed wording\n")
    dry, _ = env.sync(dry_run=True)
    assert dry.embedded > 0 and dry.removed_stale > 0
    report, count = env.sync()
    assert report.ok and count == 5 and report.embedded == 2 and report.removed_stale == 3  # p: 2 new, q: 3 kept
    assert env.sync()[0].embedded == 0


def test_removed_documents_drop_their_vectors_only_after_sync(env):
    env.sync()
    with PageIndexStore(env.docs) as store:
        store.remove_document("p", "a.md")
    service = env.service()
    bundle = service.retrieve_context("p", "why avoid hosted cloud infrastructure", 5000)
    assert not [i for i in bundle.items if i.record_kind == "document_section"]  # stale hits are re-checked
    report, count = env.sync()
    assert report.removed_stale == 3 and count == 3
