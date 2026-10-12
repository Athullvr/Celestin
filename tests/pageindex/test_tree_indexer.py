import pytest

pytest.importorskip("pageindex")

from orbit.pageindex.errors import PageIndexError
from orbit.pageindex.indexer import MAX_DOCUMENT_BYTES, index_markdown_text, index_paths
from orbit.pageindex.store import PageIndexStore
from orbit.pageindex.tree import build_sections
from tests.pageindex.fakes import DOC


def test_sections_follow_headings_with_paths_and_preamble():
    sections = build_sections(DOC, "guide")
    paths = [" > ".join(s.path) for s in sections]
    assert paths == [
        "(preamble)", "Storage Guide", "Storage Guide > Database choice",
        "Storage Guide > Backups", "Security", "Security > Authentication",
    ]
    assert "not a heading" in next(s for s in sections if s.title == "Backups").text  # fence ignored
    assert next(s for s in sections if s.title == "Database choice").parent_id == sections[1].node_id
    assert len({s.node_id for s in sections}) == len(sections)


def test_no_source_text_is_lost():
    sections = build_sections(DOC, "guide")
    joined = "\n".join(s.text for s in sections)
    for line in DOC.splitlines():
        if line.strip():
            assert line.strip() in joined


def test_heading_less_document_is_one_section():
    (only,) = build_sections("just some text\nmore text", "notes")
    assert only.title == "notes" and "more text" in only.text
    assert build_sections("   \n", "x") == []


@pytest.fixture()
def store(tmp_path):
    with PageIndexStore(tmp_path / "docs.db") as s:
        yield s


def test_indexing_is_idempotent_and_detects_changes(store):
    assert index_markdown_text(store, "p", "guide.md", DOC) == "added"
    assert index_markdown_text(store, "p", "guide.md", DOC) == "unchanged"
    assert index_markdown_text(store, "p", "guide.md", DOC + "\n## Extra\n\nnew") == "updated"
    docs = store.documents("p")
    assert len(docs) == 1 and docs[0].sections == 7  # replaced, not duplicated
    assert store.source_text("p", "guide.md").endswith("new")


def test_documents_are_project_scoped(store):
    index_markdown_text(store, "p", "guide.md", DOC)
    index_markdown_text(store, "q", "guide.md", "# Other\n\ntext")
    assert {s.project for s in store.sections("p")} == {"p"}
    assert store.get("q", "guide.md", "0001").title == "Other"
    assert store.get("p", "other.md", "0001") is None
    assert store.remove_document("p", "guide.md") and not store.sections("p") and store.sections("q")


@pytest.mark.parametrize("bad", ["", "  \n", "a\x00b", "x" * (MAX_DOCUMENT_BYTES + 1)])
def test_invalid_documents_are_rejected(store, bad):
    with pytest.raises(PageIndexError):
        index_markdown_text(store, "p", "bad.md", bad)
    assert store.documents("p") == []


def test_index_paths_handles_directories_and_bad_files(store, tmp_path):
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text(DOC)
    (root / "sub" / "b.markdown").write_text("# B\n\nbody")
    (root / "empty.md").write_text("")
    (root / "binary.md").write_bytes(b"\xff\xfe\x00bad")
    (root / "notes.txt").write_text("ignored")
    report = index_paths(store, "p", [root])
    assert sorted(report.added) == ["a.md", "sub/b.markdown"]
    assert set(report.failed) == {"empty.md", "binary.md"}
    assert not report.ok
    assert sorted(index_paths(store, "p", [root]).unchanged) == ["a.md", "sub/b.markdown"]


def test_same_filename_from_different_dirs_is_not_silently_overwritten(store, tmp_path):
    (tmp_path / "x").mkdir(); (tmp_path / "y").mkdir()
    (tmp_path / "x" / "README.md").write_text("# X\n\none")
    (tmp_path / "y" / "README.md").write_text("# Y\n\ntwo")
    report = index_paths(store, "p", [tmp_path / "x" / "README.md", tmp_path / "y" / "README.md"])
    assert report.added == ["README.md"] and "README.md" in report.failed
