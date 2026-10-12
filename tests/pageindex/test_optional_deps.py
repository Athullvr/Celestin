"""Behavior when optional dependencies are missing (must not need pageindex installed)."""

import sys

import pytest

from orbit.pageindex import cli, config
from orbit.pageindex.errors import PageIndexError, PageIndexUnavailable
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.navigator import litellm_chat
from orbit.pageindex.store import PageIndexStore


def test_indexing_without_pageindex_gives_install_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pageindex.page_index_md", None)
    monkeypatch.setitem(sys.modules, "pageindex", None)
    with PageIndexStore(tmp_path / "d.db") as store:
        with pytest.raises(PageIndexError, match=r"celestin-memory\[pageindex\]"):
            index_markdown_text(store, "p", "a.md", "# T\n\nbody")
        assert store.documents("p") == []


def test_cli_index_without_pageindex_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pageindex.page_index_md", None)
    monkeypatch.setitem(sys.modules, "pageindex", None)
    monkeypatch.setenv("CELESTIN_DB_PATH", str(tmp_path / "m.db"))
    (tmp_path / "a.md").write_text("# T\n\nbody")
    assert cli.main(["index", "--project", "p", str(tmp_path / "a.md")]) == 1
    assert "pip install" in capsys.readouterr().err


def test_litellm_missing_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(PageIndexUnavailable, match="litellm"):
        litellm_chat("openai/x")


def test_backend_builder_states(monkeypatch, tmp_path):
    monkeypatch.setenv("CELESTIN_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.delenv("CELESTIN_PAGEINDEX", raising=False)
    assert config.build_pageindex_backend() is None
    monkeypatch.setenv("CELESTIN_PAGEINDEX", "1")
    monkeypatch.delenv("CELESTIN_PAGEINDEX_MODEL", raising=False)
    backend = config.build_pageindex_backend()
    with pytest.raises(PageIndexUnavailable, match="MODEL is not set"):
        backend.retrieve("p", "some question here")
    monkeypatch.setenv("CELESTIN_PAGEINDEX_TIMEOUT", "abc")
    with pytest.raises(PageIndexUnavailable, match="must be a number"):
        config.build_pageindex_backend().retrieve("p", "some question here")
