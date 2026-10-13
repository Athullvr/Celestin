"""Heading-section retrieval as a product path (FTS5 + semantic over indexed documents)."""

import pytest

pytest.importorskip("pageindex")

from orbit.database.engine import connect
from orbit.pageindex.indexer import index_markdown_text, rebuild_project
from orbit.pageindex.sections import search_sections
from orbit.pageindex.store import PageIndexStore
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from tests.pageindex.fakes import DOC

DOC2 = "# Operations\n\n## Backups\n\nRotate the database backups weekly and verify restores.\n\n## Alerts\n\nPage the on-call engineer.\n"


@pytest.fixture()
def env(tmp_path):
    class Env:
        pass

    e = Env()
    e.conn = connect(tmp_path / "main.db")
    e.path = tmp_path / "docs.db"
    with PageIndexStore(e.path) as store:
        index_markdown_text(store, "p", "guide.md", DOC)
        index_markdown_text(store, "p", "ops.md", DOC2)
        index_markdown_text(store, "other", "guide.md", "# Secret\n\nthe other project database choice is mongodb")
    e.service = lambda **kw: RetrievalService(e.conn, sections=e.path, **kw)
    return e


def titles(service, project, query, budget=5000):
    bundle = service.retrieve_context(project, query, budget)
    return [(i.record_id, i) for i in bundle.items if i.record_kind == "document_section"]


def test_section_fts_finds_the_right_heading_with_attribution(env):
    service = env.service()
    found = titles(service, "p", "why was SQLite chosen for the database")
    assert found and found[0][0].startswith("doc:guide.md#")
    item = found[0][1]
    assert item.source_id == "guide.md" and item.status is None and "SQLite" in item.content
    source = service.last_sources[item.record_id]
    assert source["section"] == "Storage Guide > Database choice" and source["line"] > 0 and source["content_hash"]
    assert service.last_retrieval.sections == "used"


def test_exact_term_beats_unrelated_sections(env):
    ids = [rid for rid, _ in titles(env.service(), "p", "database backups")]
    assert ids[0] == "doc:ops.md#0002"


def test_project_isolation_for_sections(env):
    assert not any("mongodb" in i.content for _, i in titles(env.service(), "p", "database choice"))
    assert [i.project_id for _, i in titles(env.service(), "other", "database choice mongodb")] == ["other"]
    assert titles(env.service(), "nobody", "database choice") == []


def test_budget_is_enforced_with_sections(env):
    bundle = env.service().retrieve_context("p", "database", 300)
    assert bundle.token_count <= 300
    assert all(e.reason in {"token_budget", "duplicate_content", "draft_status", "deprecated_status"} for e in bundle.excluded)


def test_preamble_and_headingless_documents_are_searchable(env):
    with PageIndexStore(env.path) as store:
        index_markdown_text(store, "p", "plain.md", "just notes about zebra migration without headings")
    assert any(rid.startswith("doc:plain.md#") for rid, _ in titles(env.service(), "p", "zebra migration notes"))
    assert any("Intro text before any heading" in i.content for _, i in titles(env.service(), "p", "intro text before heading"))


def test_repeated_headings_and_code_blocks(env):
    md = "# A\n\n## Notes\n\nfirst notes quartz\n\n## Notes\n\nsecond notes basalt\n\n```\n# not a heading mica\n```\n"
    with PageIndexStore(env.path) as store:
        index_markdown_text(store, "p", "dup.md", md)
        secs = [s for s in store.sections("p") if s.doc_key == "dup.md"]
    assert len({s.node_id for s in secs}) == len(secs) == 3
    ids = {rid for rid, _ in titles(env.service(), "p", "second notes basalt")}
    assert any(r.startswith("doc:dup.md#") for r in ids)
    assert any("mica" in i.content for _, i in titles(env.service(), "p", "heading mica"))


def test_changed_document_replaces_its_sections_in_the_index(env):
    with PageIndexStore(env.path) as store:
        index_markdown_text(store, "p", "ops.md", "# Operations\n\n## Alerts\n\nPage the on-call engineer about pelican.\n")
    assert not any("weekly" in i.content.lower() for _, i in titles(env.service(), "p", "database backups weekly"))
    assert any("pelican" in i.content for _, i in titles(env.service(), "p", "pelican alerts"))


def test_deleted_documents_leave_the_index_only_via_explicit_maintenance(env):
    with PageIndexStore(env.path) as store:
        store.remove_document("p", "ops.md")
    assert not any(rid.startswith("doc:ops.md") for rid, _ in titles(env.service(), "p", "database backups"))


def test_section_index_is_rebuildable_and_missing_index_is_reported(env):
    with PageIndexStore(env.path) as store:
        store.connection().execute("INSERT INTO sections_fts(sections_fts) VALUES ('delete-all')")
        assert search_sections(store, "p", "database backups", 5)[0] == []
        store.rebuild_section_index()
        assert search_sections(store, "p", "database backups", 5)[0]
        rebuild_project(store, "p")
        assert search_sections(store, "p", "database backups", 5)[0]


def test_old_store_without_section_index_is_upgraded_on_open(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with PageIndexStore(path) as store:
        index_markdown_text(store, "p", "a.md", "# Title\n\nbody about walrus")
        store.connection().executescript(
            "DROP TRIGGER sections_fts_insert; DROP TRIGGER sections_fts_delete; DROP TABLE sections_fts;")
    with PageIndexStore(path) as store:  # re-open: backfilled
        assert search_sections(store, "p", "walrus", 5)[0]
    with PageIndexStore(path, create=False) as store:
        assert store.has_section_index()


def test_sections_coexist_with_chat_and_messages_keep_working(env):
    ChatMessageRepository(env.conn).insert("p", "c", "user", "we talked about database backups on friday")
    kinds = [i.record_kind for i in env.service().retrieve_context("p", "database backups", 5000).items]
    assert "chat_message" in kinds and "document_section" in kinds


def test_missing_store_file_degrades_quietly(tmp_path):
    conn = connect(tmp_path / "m.db")
    ChatMessageRepository(conn).insert("p", "c", "user", "database backups")
    service = RetrievalService(conn, sections=tmp_path / "nope.db")
    bundle = service.retrieve_context("p", "database backups", 2000)
    assert [i.record_kind for i in bundle.items] == ["chat_message"]
    assert service.last_retrieval.sections.startswith("skipped") or service.last_retrieval.sections.startswith("unavailable")
    assert not (tmp_path / "nope.db").exists()
