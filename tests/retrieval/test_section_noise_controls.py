"""Service-level behavior of the section noise controls (all default off)."""

import pytest

pytest.importorskip("pageindex")
pytest.importorskip("sqlite_vec")

from orbit.database.engine import connect
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.store import PageIndexStore
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from orbit.semantic.indexer import Indexer
from orbit.semantic.search import SemanticSearch
from orbit.semantic.vector_index import VectorIndex
from tests.semantic.fakes import FakeProvider

# Fake vectors: concept 0 = persistence words, 1 = hosted words, 2 = cooking, 3 = auth.
MD = (
    "# Guide\n\n"
    "## Persistence\n\nlocal sqlite storage database persistence hosted\n\n"
    "## Hosting\n\nhosted cloud server deployment infrastructure\n\n"
    "## Cooking\n\npasta tomato recipe cooking sqlite\n\n"
    "## Auth\n\nauth login password token hosted\n"
)


def build(tmp_path, **kw):
    class E:
        pass

    e = E()
    e.conn = connect(tmp_path / "m.db")
    e.provider = FakeProvider()
    e.vpath, e.docs = tmp_path / "v.db", tmp_path / "d.db"
    with PageIndexStore(e.docs) as store:
        index_markdown_text(store, "p", "g.md", MD)
        index_markdown_text(store, "other", "g.md", MD)
    with PageIndexStore(e.docs, create=False) as store, VectorIndex(
            e.vpath, model_id=e.provider.model_id, dimension=e.provider.dimension) as index:
        Indexer(e.conn, e.provider, index, sections_connection=store.connection()).sync()
    e.service = lambda **o: RetrievalService(
        e.conn, semantic=SemanticSearch(e.provider, e.vpath, 0.05, **{k: v for k, v in kw.items() if k == "section_margin"}),
        sections=e.docs, **{k: v for k, v in {**kw, **o}.items() if k != "section_margin"})
    return e


def section_ids(bundle):
    return [i.record_id for i in bundle.items if i.record_kind == "document_section"]


QUERY = "why avoid hosted cloud infrastructure deployment"


def test_defaults_are_unchanged(tmp_path):
    e = build(tmp_path)
    assert len(section_ids(e.service().retrieve_context("p", QUERY, 9000))) >= 2


def test_section_margin_removes_weak_sections_but_keeps_the_best(tmp_path):
    (tmp_path / "base").mkdir()
    (tmp_path / "narrow").mkdir()
    base = section_ids(build(tmp_path / "base").service().retrieve_context("p", QUERY, 9000))
    narrow = section_ids(build(tmp_path / "narrow", section_margin=0.05).service().retrieve_context("p", QUERY, 9000))
    assert narrow and set(narrow) <= set(base) and len(narrow) < len(base)
    assert narrow[0] == base[0]  # the best section survives


def test_section_margin_does_not_trim_chat_messages_or_decisions(tmp_path):
    e = build(tmp_path, section_margin=0.01)
    msgs = ChatMessageRepository(e.conn)
    for text in ("hosted cloud server deployment infrastructure", "hosted pasta recipe", "hosted cloud notes"):
        msgs.insert("p", "c", "user", text)
    with VectorIndex(e.vpath, model_id=e.provider.model_id, dimension=e.provider.dimension) as index:
        Indexer(e.conn, e.provider, index).sync(kinds=("chat_message",))
    bundle = e.service().retrieve_context("p", QUERY, 9000)
    assert sum(i.record_kind == "chat_message" for i in bundle.items) >= 2  # only sections are trimmed


def test_top_k_caps_sections_and_exempts_strong_keyword_hits(tmp_path):
    e = build(tmp_path)
    capped = e.service(section_top_k=1).retrieve_context("p", QUERY, 9000)
    assert len(section_ids(capped)) == 1
    # "login password token" matches the Auth section on every keyword (strict tier): exempt from the cap.
    service = e.service(section_top_k=1)
    bundle = service.retrieve_context("p", "login password token", 9000)
    assert any("login" in i.content for i in bundle.items)
    assert service.last_diagnostics["strategies"]["sections"]["fts_tier"] == "strict"


def test_approved_decisions_and_policy_survive_the_noise_controls(tmp_path):
    e = build(tmp_path, section_margin=0.05)
    m = ChatMessageRepository(e.conn).insert("p", "c", "user", "context")
    repo = DecisionRepository(e.conn)
    repo.save(project="p", key="ok", value="avoid hosted cloud infrastructure deployment approved", source_message_id=m, status="draft")
    repo.update_status("p", "ok", "approved")
    repo.save(project="p", key="dr", value="avoid hosted cloud infrastructure deployment draft", source_message_id=m, status="draft")
    repo.save(project="p", key="old", value="avoid hosted cloud infrastructure deployment old", source_message_id=m, status="draft")
    repo.update_status("p", "old", "deprecated")
    bundle = e.service(section_top_k=2, section_excerpt_bytes=300).retrieve_context("p", QUERY, 9000)
    decisions = [i for i in bundle.items if i.record_kind == "canonical_decision"]
    assert [d.status for d in decisions] == ["approved"] and bundle.items[0].record_kind == "canonical_decision"


def test_project_isolation_budget_and_determinism_with_controls(tmp_path):
    e = build(tmp_path, section_margin=0.05)
    first = e.service(section_top_k=3).retrieve_context("p", QUERY, 700)
    again = e.service(section_top_k=3).retrieve_context("p", QUERY, 700)
    assert first.rendered_context == again.rendered_context and first.token_count <= 700
    assert all(i.project_id == "p" for i in first.items)
    assert e.service(section_top_k=3).retrieve_context("nobody", QUERY, 9000).items == ()


def test_excerpts_keep_source_identity_and_reduce_bytes(tmp_path):
    long_md = "# Doc\n\n## Big\n\n" + "\n\n".join(f"paragraph {i} about filler words " + "z" * 200 for i in range(12)) + \
              "\n\nthe needle fact: sqlite persistence is local\n"
    e = build(tmp_path)
    with PageIndexStore(e.docs) as store:
        index_markdown_text(store, "p", "big.md", long_md)
    with PageIndexStore(e.docs, create=False) as store, VectorIndex(
            e.vpath, model_id=e.provider.model_id, dimension=e.provider.dimension) as index:
        Indexer(e.conn, e.provider, index, sections_connection=store.connection()).sync()
    plain = e.service()
    full = plain.retrieve_context("p", "needle fact sqlite persistence local", 20000)
    short_service = e.service(section_excerpt_bytes=500)
    short = short_service.retrieve_context("p", "needle fact sqlite persistence local", 20000)
    pick = lambda b: next(i for i in b.items if i.record_id.startswith("doc:big.md"))
    assert "needle fact" in pick(short).content and len(pick(short).content) < len(pick(full).content)
    source = short_service.last_sources[pick(short).record_id]
    assert source["excerpted"] is True and source["document"] == "big.md" and source["line_ranges"]
    assert "excerpted" not in plain.last_sources[pick(full).record_id]


def test_invalid_parameters_are_rejected(tmp_path):
    e = build(tmp_path)
    with pytest.raises(ValueError):
        e.service(section_top_k=0)
    with pytest.raises(ValueError):
        e.service(section_excerpt_bytes=50)
