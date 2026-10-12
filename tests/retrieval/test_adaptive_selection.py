"""Adaptive selection through RetrievalService: one primary strategy, bounded fallback, intact policy."""

import pytest

pytest.importorskip("pageindex")
pytest.importorskip("sqlite_vec")

from orbit.database.engine import connect
from orbit.pageindex.backend import PageIndexBackend, clear_navigation_cache
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.navigator import LLMTreeNavigator
from orbit.pageindex.store import PageIndexStore
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from orbit.semantic.indexer import Indexer
from orbit.semantic.search import SemanticSearch
from orbit.semantic.vector_index import VectorIndex
from tests.pageindex.fakes import DOC, FakeLLM
from tests.semantic.fakes import FakeProvider

DOC_QUERY = "what does the documentation say about the database choice"


class Env:
    def __init__(self, tmp_path, with_semantic=True, with_pageindex=True):
        clear_navigation_cache()
        self.conn = connect(tmp_path / "main.db")
        self.provider = FakeProvider()
        self.vpath = tmp_path / "v.db"
        self.docs = tmp_path / "docs.db"
        self.llm = FakeLLM(want=["database choice"])
        self.messages = ChatMessageRepository(self.conn)
        self.decisions = DecisionRepository(self.conn)
        with PageIndexStore(self.docs) as store:
            index_markdown_text(store, "p", "guide.md", DOC)
        self.with_semantic, self.with_pageindex = with_semantic, with_pageindex

    def sync(self):
        with PageIndexStore(self.docs, create=False) as store, VectorIndex(
            self.vpath, model_id=self.provider.model_id, dimension=self.provider.dimension
        ) as index:
            return Indexer(self.conn, self.provider, index, sections_connection=store.connection()).sync()

    def service(self, selector="adaptive"):
        semantic = SemanticSearch(self.provider, self.vpath, 0.3) if self.with_semantic else None
        backend = PageIndexBackend(self.docs, LLMTreeNavigator(self.llm)) if self.with_pageindex else None
        return RetrievalService(self.conn, semantic=semantic, documents=backend, sections=self.docs, selector=selector)


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


def kinds(bundle):
    return [i.record_kind for i in bundle.items]


def test_default_mode_is_unchanged_and_runs_every_enabled_strategy(env):
    env.messages.insert("p", "c", "user", "database storage choice notes")
    env.sync()
    service = env.service(selector="all")
    service.retrieve_context("p", DOC_QUERY, 5000)
    assert set(service._executed) == {"fts", "semantic", "sections", "pageindex"}
    assert service.last_retrieval.selector is None


def test_identifier_query_uses_fts_only(env):
    env.messages.insert("p", "c", "user", "failed with ERR_PAYMENT_4471 yesterday")
    service = env.service()
    bundle = service.retrieve_context("p", "ERR_PAYMENT_4471", 5000)
    assert list(service._executed) == ["fts"] and env.llm.prompts == []
    info = service.last_retrieval.selector
    assert info["primary"] == "fts" and info["fallback_used"] is False
    assert [i.record_kind for i in bundle.items] == ["chat_message"]


def test_documentation_question_uses_sections_without_a_model_call(env):
    env.sync()
    service = env.service()
    bundle = service.retrieve_context("p", DOC_QUERY, 5000)
    info = service.last_retrieval.selector
    assert info["primary"] == "sections" and not info["fallback_used"]
    assert "document_section" in kinds(bundle) and env.llm.prompts == []
    assert "pageindex" not in service._executed and service.last_retrieval.pageindex == "not_selected"


def test_bounded_fallback_when_primary_finds_nothing(env):
    service = env.service()
    # No section matches these words, so "sections" is insufficient and PageIndex runs once as the fallback.
    env.llm.want = ["database choice"]
    service.retrieve_context("p", "what does the documentation say about zzqx wwvv yyuu", 5000)
    info = service.last_retrieval.selector
    assert info["primary"] == "sections" and info["fallback"] == "pageindex" and info["fallback_used"] is True
    assert len(env.llm.prompts) == 1 and len(service._executed) <= 3  # fts decision pass + primary + fallback


def test_fallback_is_not_used_when_primary_is_sufficient(env):
    env.sync()
    service = env.service()
    service.retrieve_context("p", DOC_QUERY, 5000)
    assert service.last_retrieval.selector["fallback_used"] is False and env.llm.prompts == []


def test_approved_decisions_stay_reachable_whatever_the_primary(env):
    m = env.messages.insert("p", "c", "user", "context")
    env.decisions.save(project="p", key="k", value="documentation database choice settled sqlite", source_message_id=m, status="draft")
    env.decisions.update_status("p", "k", "approved")
    env.decisions.save(project="p", key="d", value="documentation database choice draft idea", source_message_id=m, status="draft")
    env.sync()
    service = env.service()
    bundle = service.retrieve_context("p", DOC_QUERY, 5000)
    assert service.last_retrieval.selector["primary"] == "sections"
    assert bundle.items[0].record_kind == "canonical_decision" and bundle.items[0].status == "approved"
    assert all(i.status != "draft" for i in bundle.items)


def test_semantic_primary_for_discussion_questions(env):
    env.messages.insert("p", "c", "user", "we decided against hosted cloud deployment overhead")
    env.sync()
    service = env.service()
    bundle = service.retrieve_context("p", "why did we decide to avoid hosted infrastructure", 5000)
    assert service.last_retrieval.selector["primary"] == "semantic" and "chat_message" in kinds(bundle)


def test_selector_adapts_to_missing_backends(tmp_path):
    env = Env(tmp_path, with_semantic=False, with_pageindex=False)
    env.messages.insert("p", "c", "user", "we decided against hosted cloud deployment")
    service = env.service()
    service.retrieve_context("p", "why did we decide to avoid hosted infrastructure", 5000)
    assert service.last_retrieval.selector["primary"] == "fts"
    service.retrieve_context("p", DOC_QUERY, 5000)
    assert service.last_retrieval.selector["primary"] == "sections"


def test_pageindex_failure_does_not_break_selection(env):
    env.llm.error = TimeoutError("slow")
    service = env.service()
    service.retrieve_context("p", "what does the documentation say about zzqx wwvv yyuu", 5000)
    assert service.last_retrieval.pageindex.startswith("unavailable")
    assert any("document retrieval unavailable" in w for w in service.last_retrieval.warnings)


def test_project_isolation_and_budget_under_adaptive_selection(env):
    with PageIndexStore(env.docs) as store:
        index_markdown_text(store, "other", "x.md", "# Other\n\nthe documentation database choice of another project")
    env.sync()
    service = env.service()
    bundle = service.retrieve_context("p", DOC_QUERY, 400)
    assert bundle.token_count <= 400 and all(i.project_id == "p" for i in bundle.items)


def test_invalid_selector_value_is_rejected(env):
    with pytest.raises(ValueError):
        RetrievalService(env.conn, selector="llm")
