"""Strategy interface: normalized candidates from every retrieval method."""

import pytest

pytest.importorskip("pageindex")
pytest.importorskip("sqlite_vec")

from orbit.database.engine import connect
from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.errors import PageIndexUnavailable
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.navigator import LLMTreeNavigator
from orbit.pageindex.store import PageIndexStore
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval.fts import FtsMessageSearch
from orbit.retrieval.service import DECISION_FTS_SCHEMA, MESSAGE_FTS_SCHEMA
from orbit.retrieval.strategies import (
    Candidate, FtsStrategy, PageIndexStrategy, RetrievalRequest, SectionStrategy, SemanticStrategy,
)
from orbit.semantic.indexer import Indexer
from orbit.semantic.search import SemanticSearch
from orbit.semantic.vector_index import VectorIndex
from tests.pageindex.fakes import DOC, FakeLLM
from tests.semantic.fakes import FakeProvider


@pytest.fixture()
def env(tmp_path):
    class E:
        pass

    e = E()
    e.conn = connect(tmp_path / "m.db")
    e.docs, e.vpath = tmp_path / "d.db", tmp_path / "v.db"
    e.provider = FakeProvider()
    m = ChatMessageRepository(e.conn).insert("p", "c", "user", "database storage choice discussed hosted cloud")
    repo = DecisionRepository(e.conn)
    repo.save(project="p", key="k", value="database storage choice approved", source_message_id=m, status="draft")
    repo.update_status("p", "k", "approved")
    ChatMessageRepository(e.conn).insert("other", "c", "user", "database storage choice of another project")
    with PageIndexStore(e.docs) as store:
        index_markdown_text(store, "p", "guide.md", DOC)
    with PageIndexStore(e.docs, create=False) as store, VectorIndex(
            e.vpath, model_id=e.provider.model_id, dimension=e.provider.dimension) as index:
        Indexer(e.conn, e.provider, index, sections_connection=store.connection()).sync()
    e.semantic = SemanticSearch(e.provider, e.vpath, 0.1)
    e.request = RetrievalRequest("p", "database storage choice", 20, 4000)
    return e


def check_normalized(c: Candidate):
    assert c.record_id and c.record_type in {"chat_message", "canonical_decision", "document_section"}
    assert c.project == "p" and c.content and c.method and c.rank >= 1
    if c.record_type == "canonical_decision":
        assert c.status in {"approved", "draft", "deprecated"}
    else:
        assert c.status is None
    if c.record_type == "document_section":
        assert {"document", "section", "node_id", "line", "content_hash"} <= set(c.source)


def test_fts_strategy_returns_messages_and_decisions_with_status(env):
    repo = DecisionRepository(env.conn)
    result = FtsStrategy(FtsMessageSearch(env.conn, MESSAGE_FTS_SCHEMA), FtsMessageSearch(env.conn, DECISION_FTS_SCHEMA),
                         repo).retrieve(env.request)
    assert {c.record_type for c in result.candidates} == {"chat_message", "canonical_decision"}
    assert all(c.method == "fts" and c.score is not None for c in result.candidates)
    [check_normalized(c) for c in result.candidates]
    only = FtsStrategy(FtsMessageSearch(env.conn, MESSAGE_FTS_SCHEMA), FtsMessageSearch(env.conn, DECISION_FTS_SCHEMA),
                       repo).retrieve(env.request, kinds=("canonical_decision",))
    assert {c.record_type for c in only.candidates} == {"canonical_decision"}


def test_semantic_strategy_reloads_authoritative_rows_and_isolates_projects(env):
    strat = SemanticStrategy(env.semantic, env.conn, DecisionRepository(env.conn))
    result = strat.retrieve(RetrievalRequest("p", "hosted cloud storage", 20, 4000))
    assert result.status == "ok" and result.candidates
    [check_normalized(c) for c in result.candidates]
    assert {c.method for c in result.candidates} == {"semantic"}


def test_semantic_strategy_reports_unavailable_without_candidates(env):
    env.provider.fail = True
    result = SemanticStrategy(env.semantic, env.conn, DecisionRepository(env.conn)).retrieve(env.request)
    assert result.status == "unavailable" and result.candidates == [] and "outage" in result.detail


def test_section_strategy_has_fts_and_semantic_methods(env):
    strat = SectionStrategy(env.docs, env.semantic)
    assert strat.has_documents("p") and not strat.has_documents("nobody")
    result = strat.retrieve(RetrievalRequest("p", "database storage choice", 20, 4000))
    assert {"sections_fts", "sections_semantic"} <= {c.method for c in result.candidates}
    [check_normalized(c) for c in result.candidates]
    assert SectionStrategy(env.docs, None).retrieve(RetrievalRequest("nobody", "x y z", 5, 1000)).status == "skipped"


def test_pageindex_strategy_statuses(env):
    ok = PageIndexStrategy(PageIndexBackend(env.docs, LLMTreeNavigator(FakeLLM(want=["database choice"]))))
    result = ok.retrieve(RetrievalRequest("p", "why did we pick this storage layer", 5, 4000))
    assert result.status == "ok" and result.candidates[0].method == "pageindex" and result.navigation
    check_normalized(result.candidates[0])
    skipped = ok.retrieve(RetrievalRequest("p", "ERR_4471", 5, 4000))
    assert skipped.status == "skipped" and "identifier" in skipped.detail
    broken = PageIndexStrategy(PageIndexBackend(env.docs, LLMTreeNavigator(FakeLLM(error=TimeoutError("x")))))
    assert broken.retrieve(RetrievalRequest("p", "why did we pick this storage layer", 5, 4000)).status == "unavailable"
    assert PageIndexStrategy(PageIndexBackend.unavailable("no model")).retrieve(env.request).status == "unavailable"
