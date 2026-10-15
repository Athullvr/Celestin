"""MCP-level and CLI behavior for document retrieval (fake navigation model)."""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("pageindex")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from orbit.mcp_server import server
from orbit.mcp_server.persistence_services import PersistenceServices
from orbit.mcp_server.retrieval_services import RetrievalServices
from orbit.pageindex import cli, config
from tests.pageindex.fakes import DOC, FakeLLM

QUERY = "database choice rationale"


@pytest.fixture()
def docs_env(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    llm = FakeLLM(want=["database choice"])
    monkeypatch.setenv("CELESTIN_DB_PATH", str(db))
    monkeypatch.setenv("CELESTIN_PAGEINDEX", "1")
    monkeypatch.setenv("CELESTIN_PAGEINDEX_MODEL", "fake/model")
    monkeypatch.setattr(config, "litellm_chat", lambda model, timeout=30.0, **kw: llm)
    monkeypatch.setattr("orbit.database.engine.DB_PATH", db)
    monkeypatch.setattr(server, "persistence_services", PersistenceServices(db))
    monkeypatch.setattr(server, "retrieval_services", RetrievalServices(db))
    from orbit.pageindex.backend import clear_navigation_cache
    clear_navigation_cache()
    (tmp_path / "guide.md").write_text(DOC)
    assert cli.main(["index", "--project", "demo", str(tmp_path / "guide.md")]) == 0
    return db, llm, tmp_path


def test_retrieve_context_tool_returns_document_sections_with_source(docs_env):
    db, llm, _ = docs_env
    message = server.ingest_chat_message("demo", "c1", "user", "we discussed the database choice rationale")
    result = server.retrieve_context("demo", QUERY, 2000)
    assert result["retrieval"]["pageindex"] == "used" and result["retrieval"]["warnings"] == []
    by_kind = {i["record_kind"]: i for i in result["items"]}
    section = by_kind["document_section"]
    assert section["source_message_id"] is None
    assert section["source"]["document"] == "guide.md"
    assert section["source"]["section"] == "Storage Guide > Database choice"
    assert section["source"]["content_hash"] and "SQLite" in section["content"]
    assert by_kind["chat_message"]["source_message_id"] == message["message_id"]
    assert "source" not in by_kind["chat_message"]
    assert result["token_count"] <= result["token_budget"]


def test_navigation_stats_are_reported_and_cache_hits_are_visible(docs_env):
    first = server.retrieve_context("demo", QUERY, 2000)["retrieval"]["navigation"]
    assert first["outcome"] == "ok" and first["elapsed_ms"] >= 0 and first["est_prompt_tokens"] > 0
    assert first["cache_hit"] is False
    second = server.retrieve_context("demo", QUERY, 2000)["retrieval"]["navigation"]
    assert second["cache_hit"] is True


def test_other_tools_unaffected_and_survive_navigation_failure(docs_env, monkeypatch):
    db, llm, _ = docs_env
    llm.error = RuntimeError("provider down")
    saved = server.ingest_chat_message("demo", "c1", "user", "we discussed the database choice rationale")
    decision = server.save_decision("demo", "k", "use sqlite for database choice", saved["message_id"])
    assert decision["status"] == "draft"
    found = server.search_chat_history("demo", "database", 5)
    assert [r["message_id"] for r in found["results"]] == [saved["message_id"]]
    assert "retrieval" not in found
    context = server.retrieve_context("demo", QUERY, 2000)
    assert context["retrieval"]["pageindex"].startswith("unavailable")
    kinds = {i["record_kind"] for i in context["items"]}
    assert "chat_message" in kinds  # ordinary retrieval is unaffected; heading sections may also match
    assert context["retrieval"]["sections"] == "used"
    assert server.ping() == "Celestin MCP server is running."


def test_missing_model_reports_unavailable_without_breaking(docs_env, monkeypatch):
    monkeypatch.delenv("CELESTIN_PAGEINDEX_MODEL")
    result = server.retrieve_context("demo", QUERY, 2000)
    assert "CELESTIN_PAGEINDEX_MODEL is not set" in result["retrieval"]["pageindex"]


def test_response_schema_unchanged_when_disabled(docs_env, monkeypatch):
    monkeypatch.delenv("CELESTIN_PAGEINDEX")
    monkeypatch.setenv("CELESTIN_DOC_SECTIONS", "0")
    assert "retrieval" not in server.retrieve_context("demo", QUERY, 2000)


def test_missing_litellm_degrades(docs_env, monkeypatch):
    def boom(model, timeout=30.0, **kw):
        from orbit.pageindex.errors import PageIndexUnavailable
        raise PageIndexUnavailable("litellm is not installed")
    monkeypatch.setattr(config, "litellm_chat", boom)
    assert "litellm is not installed" in server.retrieve_context("demo", QUERY, 2000)["retrieval"]["pageindex"]


def test_cli_index_status_remove_and_failures(docs_env, capsys):
    db, _, tmp = docs_env
    capsys.readouterr()
    assert cli.main(["index", "--project", "demo", str(tmp / "guide.md")]) == 0
    assert "unchanged: guide.md" in capsys.readouterr().out
    (tmp / "guide.md").write_text(DOC + "\n## More\n\nx")
    cli.main(["index", "--project", "demo", str(tmp / "guide.md")])
    assert "updated: guide.md" in capsys.readouterr().out
    assert cli.main(["status", "--project", "demo"]) == 0
    assert "1 document(s)" in capsys.readouterr().out
    (tmp / "bad.md").write_text("")
    assert cli.main(["index", "--project", "demo", str(tmp / "bad.md")]) == 1
    assert cli.main(["index", "--project", "demo", str(tmp / "empty-dir-missing")]) == 1
    assert cli.main(["remove", "--project", "demo", "guide.md"]) == 0
    assert cli.main(["remove", "--project", "demo", "guide.md"]) == 1


def test_cli_search_prints_sections(docs_env, capsys):
    capsys.readouterr()
    assert cli.main(["search", "--project", "demo", QUERY]) == 0
    assert "guide.md :: Storage Guide > Database choice" in capsys.readouterr().out


def test_cli_status_without_index_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("orbit.database.engine.DB_PATH", tmp_path / "x.db")
    assert cli.main(["status", "--project", "demo"]) == 1
    assert "celestin-docs index" in capsys.readouterr().err


def _script(name):
    return shutil.which(name, path=f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")


def test_stdio_server_still_serves_all_tools_with_pageindex_enabled_but_unconfigured(tmp_path):
    """Real stdio protocol: PageIndex enabled without a model must not break any tool."""
    async def run():
        env = {
            **os.environ,
            "CELESTIN_DB_PATH": str(tmp_path / "m.db"),
            "CELESTIN_PAGEINDEX": "1",
            "CELESTIN_LOCAL_PROJECT_ACCESS": json.dumps({"p": ["read", "write"]}),
        }
        env.pop("CELESTIN_PAGEINDEX_MODEL", None)
        executable = _script("celestin")
        command, args = (executable, []) if executable else (sys.executable, ["-m", "orbit.mcp_server.server"])
        params = StdioServerParameters(command=command, args=args, cwd=Path(__file__).resolve().parents[2], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                assert tools == {"ping", "ingest_chat_message", "save_decision", "search_chat_history", "retrieve_context"}
                ingest = await session.call_tool("ingest_chat_message", {
                    "project": "p", "conversation_id": "c", "role": "user", "content": "database storage choice"})
                assert not ingest.isError
                ctx = await session.call_tool("retrieve_context", {
                    "project": "p", "query": "database storage choice", "token_budget": 2000})
                assert not ctx.isError
                payload = json.loads(ctx.content[0].text)
                assert payload["retrieval"]["pageindex"].startswith("unavailable")
                assert [i["record_kind"] for i in payload["items"]] == ["chat_message"]
    asyncio.run(run())


def test_selector_env_switches_mode_and_default_keeps_all_strategies(docs_env, monkeypatch):
    server.ingest_chat_message("demo", "c1", "user", "we discussed the database choice rationale")
    default = server.retrieve_context("demo", QUERY, 2000)
    assert "selector" not in default["retrieval"] and default["retrieval"]["sections"] == "used"
    monkeypatch.setenv("CELESTIN_RETRIEVAL_SELECTOR", "adaptive")
    adaptive = server.retrieve_context("demo", QUERY, 2000)
    sel = adaptive["retrieval"]["selector"]
    assert sel["mode"] == "adaptive" and sel["primary"] in {"fts", "semantic", "sections", "pageindex"}
    assert len(sel["executed"]) <= 3
    monkeypatch.setenv("CELESTIN_RETRIEVAL_SELECTOR", "nonsense")
    assert "selector" not in server.retrieve_context("demo", QUERY, 2000)["retrieval"]  # unknown value: established behavior


def test_pageindex_stays_disabled_by_default(docs_env, monkeypatch):
    monkeypatch.delenv("CELESTIN_PAGEINDEX")
    monkeypatch.delenv("CELESTIN_PAGEINDEX_MODEL")
    result = server.retrieve_context("demo", QUERY, 2000)
    assert "pageindex" not in result["retrieval"]  # sections work; no model, no navigation, no PageIndex status
    assert result["retrieval"]["sections"] == "used"


def test_noise_control_env_vars_through_the_mcp_tool(docs_env, monkeypatch):
    base = server.retrieve_context("demo", QUERY, 5000)
    monkeypatch.setenv("CELESTIN_SECTION_TOP_K", "1")
    capped = server.retrieve_context("demo", QUERY, 5000)
    assert len([i for i in capped["items"] if i["record_kind"] == "document_section"]) <= 1
    assert set(capped) == set(base)  # response schema is unchanged
    monkeypatch.setenv("CELESTIN_SECTION_TOP_K", "not-a-number")
    monkeypatch.setenv("CELESTIN_SECTION_EXCERPT_BYTES", "50")  # below the minimum: ignored, not an error
    ignored = server.retrieve_context("demo", QUERY, 5000)
    assert [i["record_id"] for i in ignored["items"]] == [i["record_id"] for i in base["items"]]
