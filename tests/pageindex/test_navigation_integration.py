import json

import pytest

from orbit.database.engine import connect
from orbit.pageindex.backend import PageIndexBackend, route
from orbit.pageindex.errors import PageIndexUnavailable
from orbit.pageindex.navigator import LLMTreeNavigator, OutlineEntry
from orbit.pageindex.store import PageIndexStore
from orbit.pageindex.tree import Section
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from tests.pageindex.fakes import FakeLLM

QUERY = "database storage choice"


def sections():
    return [
        Section("0001", None, "Storage Guide", ("Storage Guide",), 1, 1, "# Storage Guide\n\nOverview."),
        Section("0002", "0001", "Database choice", ("Storage Guide", "Database choice"), 2, 3,
                "## Database choice\n\nWe chose SQLite because it needs no server."),
        Section("0003", "0001", "Backups", ("Storage Guide", "Backups"), 2, 7, "## Backups\n\nCopy nightly."),
    ]


@pytest.fixture()
def env(tmp_path):
    class Env:
        pass

    e = Env()
    e.conn = connect(tmp_path / "main.db")
    e.store_path = tmp_path / "docs.db"
    with PageIndexStore(e.store_path) as store:
        for project in ("p", "other"):
            store.upsert_document(project, "guide.md", "/x/guide.md", "src", "guide", sections(), "t1")
    e.messages = ChatMessageRepository(e.conn)
    e.decisions = DecisionRepository(e.conn)

    def service(llm=None, **kw):
        llm = llm or FakeLLM(want=["database choice"])
        backend = PageIndexBackend(e.store_path, LLMTreeNavigator(llm), **kw)
        return RetrievalService(e.conn, documents=backend), llm

    e.service = service
    return e


# ---- navigator ------------------------------------------------------------

OUTLINE = [OutlineEntry("d.md", "0001", ("A",), "a"), OutlineEntry("d.md", "0002", ("A", "B"), "b")]


def test_parse_ignores_unknown_refs_duplicates_and_respects_limit():
    reply = 'noise {"thinking": "x", "sections": ["S2", "S2", "S9", "bogus", "S1"]} trailing'
    assert LLMTreeNavigator.parse(reply, OUTLINE, 5) == [("d.md", "0002"), ("d.md", "0001")]
    assert LLMTreeNavigator.parse(reply, OUTLINE, 1) == [("d.md", "0002")]
    assert LLMTreeNavigator.parse('{"sections": []}', OUTLINE, 3) == []


@pytest.mark.parametrize("reply", ["", "not json", '{"nodes": []}', '{"sections": "S1"}', "{broken"])
def test_unparseable_replies_are_unavailable_not_fabricated(reply):
    with pytest.raises(PageIndexUnavailable):
        LLMTreeNavigator.parse(reply, OUTLINE, 3)


def test_navigator_wraps_model_errors_and_limits_outline_size():
    nav = LLMTreeNavigator(FakeLLM(error=TimeoutError("slow")))
    with pytest.raises(PageIndexUnavailable, match="TimeoutError"):
        nav.select("q", OUTLINE, 3)
    with pytest.raises(PageIndexUnavailable, match="limit"):
        LLMTreeNavigator(FakeLLM(), max_outline=1).select("q", OUTLINE, 3)


def test_prompt_contains_outline_snippets_not_full_documents():
    llm = FakeLLM(reply='{"sections": []}')
    long_text = "word " * 500
    LLMTreeNavigator(llm).select("question", [OutlineEntry("d.md", "1", ("T",), long_text)], 3)
    assert "S1 | d.md | T |" in llm.prompts[0] and len(llm.prompts[0]) < 1500


@pytest.mark.parametrize("query, skipped", [("ERR_PAYMENT_4471", True), ("login bug", True), (QUERY, False)])
def test_routing_skips_short_identifier_queries(query, skipped):
    assert (route(query) is not None) is skipped


# ---- retrieval integration ------------------------------------------------

def test_document_section_enters_context_with_source_reference(env):
    service, llm = env.service()
    bundle = service.retrieve_context("p", QUERY, 2000)
    (item,) = bundle.items
    assert item.record_kind == "document_section" and item.status is None
    assert item.record_id == "doc:guide.md#0002" and item.source_id == "guide.md"
    assert "SQLite" in item.content and item.project_id == "p"
    assert service.last_sources[item.record_id]["section"] == "Storage Guide > Database choice"
    assert service.last_retrieval.pageindex == "used"
    assert len(llm.prompts) == 1


def test_documents_combine_with_messages_and_decisions_without_losing_policy(env):
    m = env.messages.insert("p", "c", "user", "we talked about the database storage choice")
    env.decisions.save(project="p", key="k", value="database storage choice approved", source_message_id=m, status="draft")
    env.decisions.update_status("p", "k", "approved")
    env.decisions.save(project="p", key="d", value="database storage choice draft idea", source_message_id=m, status="draft")
    service, _ = env.service()
    bundle = service.retrieve_context("p", QUERY, 5000)
    kinds = [i.record_kind for i in bundle.items]
    assert kinds[0] == "canonical_decision" and bundle.items[0].status == "approved"
    assert {"chat_message", "document_section"} <= set(kinds)
    assert all(i.status != "draft" for i in bundle.items)
    assert len({i.record_id for i in bundle.items}) == len(bundle.items)


def test_project_isolation_and_unknown_project(env):
    service, _ = env.service()
    assert {i.project_id for i in service.retrieve_context("p", QUERY, 2000).items} == {"p"}
    bundle = service.retrieve_context("nobody", QUERY, 2000)
    assert bundle.items == () and service.last_retrieval.pageindex == "no_documents"


def test_budget_is_enforced_for_document_sections(env):
    service, _ = env.service()
    bundle = service.retrieve_context("p", QUERY, 100)
    assert bundle.token_count <= 100 and bundle.items == ()
    assert any(e.reason == "token_budget" for e in bundle.excluded)


def test_short_query_skips_the_model_call(env):
    env.messages.insert("p", "c", "user", "ERR4711 happened")
    service, llm = env.service()
    bundle = service.retrieve_context("p", "ERR4711", 2000)
    assert llm.prompts == [] and service.last_retrieval.pageindex.startswith("skipped")
    assert [i.record_kind for i in bundle.items] == ["chat_message"]


def test_model_chooses_nothing_is_a_normal_empty_result(env):
    service, _ = env.service(FakeLLM(reply='{"sections": []}'))
    assert service.retrieve_context("p", QUERY, 2000).items == ()
    assert service.last_retrieval.pageindex == "used"


def test_navigator_failure_degrades_to_existing_retrieval(env):
    env.messages.insert("p", "c", "user", "the database storage choice was sqlite")
    service, _ = env.service(FakeLLM(error=ConnectionError("down")))
    bundle = service.retrieve_context("p", QUERY, 2000)
    assert [i.record_kind for i in bundle.items] == ["chat_message"]
    assert service.last_retrieval.pageindex.startswith("unavailable")
    assert "document retrieval unavailable" in service.last_retrieval.warnings[0]


def test_missing_store_and_missing_model_degrade(env, tmp_path):
    env.messages.insert("p", "c", "user", "the database storage choice was sqlite")
    for backend, needle in [
        (PageIndexBackend(tmp_path / "none.db", LLMTreeNavigator(FakeLLM())), "celestin-docs index"),
        (PageIndexBackend.unavailable("no navigation model configured"), "no navigation model"),
    ]:
        service = RetrievalService(env.conn, documents=backend)
        bundle = service.retrieve_context("p", QUERY, 2000)
        assert len(bundle.items) == 1 and needle in service.last_retrieval.pageindex
    assert not (tmp_path / "none.db").exists()


def test_hallucinated_references_cannot_create_sources(env):
    service, _ = env.service(FakeLLM(reply=json.dumps({"sections": ["S99", "doc:evil#1"]})))
    assert service.retrieve_context("p", QUERY, 2000).items == ()


def test_disabled_documents_leave_existing_behavior_unchanged(env):
    env.messages.insert("p", "c", "user", "database storage choice")
    service = RetrievalService(env.conn)
    bundle = service.retrieve_context("p", QUERY, 2000)
    assert service.last_retrieval.pageindex is None and not service.documents_enabled
    assert [i.record_kind for i in bundle.items] == ["chat_message"]
    assert bundle.items[0].relevance_score < 0 and abs(bundle.items[0].relevance_score) < 1e-3  # raw BM25
