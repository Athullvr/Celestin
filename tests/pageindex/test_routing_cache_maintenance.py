import logging
import threading

import pytest

from orbit.database.engine import connect
from orbit.pageindex import cli
from orbit.pageindex.backend import PageIndexBackend, clear_navigation_cache
from orbit.pageindex.errors import PageIndexUnavailable
from orbit.pageindex.indexer import index_markdown_text, rebuild_project
from orbit.pageindex.navigator import LLMTreeNavigator, _Chat, missing_credentials
from orbit.pageindex.routing import decide_route, has_identifier
from orbit.pageindex.store import PageIndexStore
from orbit.pageindex.tree import Section
from tests.pageindex.fakes import FakeLLM

Q = "why did we choose this storage layer"


# ---- routing policy -------------------------------------------------------

@pytest.mark.parametrize("query, ident", [
    ("ERR_PAYMENT_4471", True), ("open src/app/main.py please", True), ("README.md", True),
    ("what changed in v1.2.3", True), ("error E4711 on login", True), ("snake_case_name", True),
    ("what does phase 8 conclude about tunnels", False), ("why did we choose sqlite", False),
    ("is it 100% done?", False), ("the end.", False),
])
def test_identifier_detection(query, ident):
    assert has_identifier(query) is ident


@pytest.mark.parametrize("kwargs, use, fragment", [
    (dict(query=Q, token_budget=2000), True, "natural-language"),
    (dict(query="ERR_4471 on checkout please explain", token_budget=2000), False, "identifier"),
    (dict(query="login bug", token_budget=2000), False, "fewer than"),
    (dict(query=Q, token_budget=499), False, "budget"),
    (dict(query=Q, token_budget=2000, outline_tokens=50_000), False, "outline too large"),
    (dict(query=Q, token_budget=2000, approved_strict_hit=True), False, "approved decision"),
])
def test_route_decisions(kwargs, use, fragment):
    decision = decide_route(**kwargs)
    assert decision.use is use and fragment in decision.reason


# ---- navigation cache, stats, project isolation ---------------------------

def sec(text="body"):
    return [Section("0001", None, "Database choice", ("Database choice",), 1, 1, "# Database choice\n\n" + text)]


@pytest.fixture()
def backend_env(tmp_path):
    clear_navigation_cache()
    path = tmp_path / "docs.db"
    with PageIndexStore(path) as store:
        store.upsert_document("a", "d.md", None, "src-a", "d", sec("alpha"), "t1")
        store.upsert_document("b", "d.md", None, "src-b", "d", sec("beta"), "t1")
    llm = FakeLLM(want=["database"])

    def make(**kw):
        return PageIndexBackend(path, LLMTreeNavigator(llm), cache_size=8, cache_namespace="m", **kw)

    yield path, llm, make
    clear_navigation_cache()


def test_cache_hit_skips_the_model_and_is_keyed_by_project(backend_env):
    path, llm, make = backend_env
    backend = make()
    first = backend.retrieve("a", Q)
    assert len(llm.prompts) == 1 and not backend.last_stats.cache_hit
    again = make().retrieve("a", "  WHY did we  choose this storage layer ")  # new backend, normalized query
    assert len(llm.prompts) == 1 and make().last_stats is None
    assert [s.text for s in again] == [s.text for s in first]
    other = backend.retrieve("b", Q)
    assert len(llm.prompts) == 2 and other[0].project == "b" and other[0].text != first[0].text


def test_cache_invalidates_when_the_index_changes(backend_env):
    path, llm, make = backend_env
    backend = make()
    backend.retrieve("a", Q)
    with PageIndexStore(path) as store:
        store.upsert_document("a", "d.md", None, "src-a2", "d", sec("alpha changed"), "t1")
    result = backend.retrieve("a", Q)
    assert len(llm.prompts) == 2 and "alpha changed" in result[0].text


def test_failures_are_not_cached(backend_env):
    path, llm, make = backend_env
    llm.error = TimeoutError("slow")
    backend = make()
    with pytest.raises(PageIndexUnavailable):
        backend.retrieve("a", Q)
    assert backend.last_stats.outcome == "error"
    llm.error = None
    assert backend.retrieve("a", Q) and len(llm.prompts) == 2


def test_stats_report_observed_usage_and_estimates(backend_env):
    path, llm, make = backend_env
    llm.last_usage = {"prompt_tokens": 123, "completion_tokens": 7}
    backend = make()
    backend.retrieve("a", Q)
    stats = backend.last_stats
    assert stats.usage == {"prompt_tokens": 123, "completion_tokens": 7}
    assert stats.est_prompt_tokens > 0 and stats.prompt_chars > 0 and stats.elapsed_ms >= 0
    assert set(stats.as_dict()) >= {"outcome", "elapsed_ms", "cache_hit", "est_prompt_tokens", "usage"}


def test_cache_can_be_disabled(backend_env):
    path, llm, _ = backend_env
    backend = PageIndexBackend(path, LLMTreeNavigator(llm), cache_size=0)
    backend.retrieve("a", Q); backend.retrieve("a", Q)
    assert len(llm.prompts) == 2


# ---- LiteLLM wrapper: bounded retries, usage, credentials -----------------

class FakeLitellm:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def completion(self, **kw):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Resp:
    class usage:
        prompt_tokens, completion_tokens = 50, 5

    class _M:
        content = '{"sections": []}'

    class _C:
        message = None

    choices = [_C()]
    choices[0].message = _M()


class StatusError(Exception):
    def __init__(self, status):
        self.status_code = status


def test_chat_retries_are_bounded_and_skip_unrecoverable_errors():
    ok = FakeLitellm([ConnectionError("x"), Resp()])
    assert _Chat(ok, "m", 5, retries=1)('p') == '{"sections": []}' and ok.calls == 2
    assert _Chat(ok, "m", 5, retries=1).last_usage is None
    flaky = FakeLitellm([ConnectionError("x")] * 5)
    with pytest.raises(ConnectionError):
        _Chat(flaky, "m", 5, retries=2)("p")
    assert flaky.calls == 3
    auth = FakeLitellm([StatusError(401), Resp()])
    with pytest.raises(StatusError):
        _Chat(auth, "m", 5, retries=3)("p")
    assert auth.calls == 1
    chat = _Chat(FakeLitellm([Resp()]), "m", 5, retries=0)
    chat("p")
    assert chat.last_usage == {"prompt_tokens": 50, "completion_tokens": 5}


def test_missing_credentials_is_safe_without_litellm(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "litellm", None)
    assert missing_credentials("openai/x") == []


def test_logs_never_contain_prompts_or_document_text(backend_env, caplog):
    path, llm, make = backend_env
    llm.error = RuntimeError("provider said: SECRET-DOC-TEXT")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(PageIndexUnavailable) as raised:
            make().retrieve("a", Q)
    assert "SECRET-DOC-TEXT" not in str(raised.value) and "alpha" not in caplog.text
    assert Q not in caplog.text


# ---- index maintenance ----------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    with PageIndexStore(tmp_path / "m.db") as s:
        yield s


def test_bold_only_lines_do_not_become_headings_when_real_headings_exist(store):
    pytest.importorskip("pageindex")
    from orbit.pageindex.tree import build_sections

    md = "# Install\n\n**macOS / Linux**\n\n```sh\npip install x\n```\n\n**Windows**\n\nrun it\n\n## Usage\n\ntext\n"
    sections = build_sections(md, "readme")
    assert [" > ".join(s.path) for s in sections] == ["Install", "Install > Usage"]
    assert "**Windows**" in sections[0].text and "pip install x" in sections[0].text  # nothing lost
    only_bold = build_sections("**Part one**\n\ntext\n\n**Part two**\n\nmore", "doc")
    assert [s.title for s in only_bold] == ["Part one", "Part two"]  # no # headings: keep PageIndex behavior


def test_old_tree_schema_triggers_reindex(store):
    pytest.importorskip("pageindex")
    store.upsert_document("p", "a.md", None, "# T\n\nbody", "a", sec(), "pageindex-md-v1")
    assert index_markdown_text(store, "p", "a.md", "# T\n\nbody") == "updated"
    assert index_markdown_text(store, "p", "a.md", "# T\n\nbody") == "unchanged"


def test_fingerprint_tracks_changes_per_project(store):
    store.upsert_document("a", "d.md", None, "one", "d", sec(), "t")
    f1 = store.fingerprint("a")
    store.upsert_document("b", "d.md", None, "two", "d", sec(), "t")
    assert store.fingerprint("a") == f1
    store.upsert_document("a", "d.md", None, "three", "d", sec(), "t")
    assert store.fingerprint("a") != f1
    assert store.fingerprint("empty") == store.fingerprint("empty2")


def test_deleted_sources_are_reported_and_only_pruned_explicitly(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pageindex")
    monkeypatch.setattr("orbit.database.engine.DB_PATH", tmp_path / "m.db")
    (tmp_path / "keep.md").write_text("# Keep\n\nx")
    (tmp_path / "gone.md").write_text("# Gone\n\ny")
    assert cli.main(["index", "--project", "p", str(tmp_path / "keep.md"), str(tmp_path / "gone.md")]) == 0
    (tmp_path / "gone.md").unlink()
    assert cli.main(["index", "--project", "p", str(tmp_path / "keep.md")]) == 0  # normal indexing deletes nothing
    capsys.readouterr()
    cli.main(["status", "--project", "p"])
    out = capsys.readouterr().out
    assert "gone.md" in out and "MISSING SOURCE" in out and "2 document(s)" in out
    assert cli.main(["prune", "--project", "p"]) == 0 and "would remove: gone.md" in capsys.readouterr().out
    cli.main(["status", "--project", "p"]); assert "2 document(s)" in capsys.readouterr().out
    assert cli.main(["prune", "--project", "p", "--yes"]) == 0
    cli.main(["status", "--project", "p"]); out = capsys.readouterr().out
    assert "1 document(s)" in out and "keep.md" in out
    assert (tmp_path / "keep.md").exists()


def test_rebuild_rederives_trees_from_stored_text_without_sources(store):
    pytest.importorskip("pageindex")
    index_markdown_text(store, "p", "a.md", "# T\n\nbody\n\n## S\n\nmore", source_path="/does/not/exist.md")
    store._conn.execute("DELETE FROM sections")  # simulate a damaged derived index
    assert store.sections("p") == []
    report = rebuild_project(store, "p")
    assert report.ok and report.updated == ["a.md"] and len(store.sections("p")) == 2


def test_concurrent_indexing_from_two_connections(tmp_path):
    path = tmp_path / "c.db"
    PageIndexStore(path).close()
    errors = []

    def work(project):
        try:
            with PageIndexStore(path) as s:
                for i in range(20):
                    s.upsert_document(project, f"d{i}.md", None, f"text {project} {i}", "d", sec(), "t")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in ("a", "b")]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors
    with PageIndexStore(path) as s:
        assert len(s.documents("a")) == len(s.documents("b")) == 20
