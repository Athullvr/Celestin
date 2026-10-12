"""Index Markdown files into the document store (idempotent, change-aware)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import PageIndexError
from .store import PageIndexStore
from .tree import TREE_SCHEMA, build_sections

MAX_DOCUMENT_BYTES = 2_000_000
MARKDOWN_SUFFIXES = {".md", ".markdown"}


@dataclass
class IndexReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def index_markdown_text(
    store: PageIndexStore, project: str, doc_key: str, text: str, *, source_path: str | None = None
) -> str:
    """Index one document's text under a stable ``doc_key``. Returns added|updated|unchanged."""
    if not project.strip() or not doc_key.strip():
        raise PageIndexError("project and doc_key must be non-empty")
    if "\x00" in text or not text.strip():
        raise PageIndexError("document must be non-empty text without NUL characters")
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise PageIndexError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    title = Path(doc_key).stem or doc_key
    sections = build_sections(text, title)
    if not sections:
        raise PageIndexError("document has no indexable content")
    return store.upsert_document(project, doc_key, source_path, text, title, sections, TREE_SCHEMA)


def _files(paths: list[Path]) -> list[tuple[Path, Path]]:
    """(file, root) pairs; the doc key is the file's path relative to its root."""
    found = []
    for path in paths:
        if path.is_dir():
            found += [(f, path) for f in sorted(path.rglob("*")) if f.suffix.lower() in MARKDOWN_SUFFIXES and f.is_file()]
        else:
            found.append((path, path.parent))
    return found


def index_paths(store: PageIndexStore, project: str, paths: list[str | Path]) -> IndexReport:
    """Index files and directories (recursively, ``.md``/``.markdown``). One bad file never stops the rest."""
    report = IndexReport()
    seen: set[str] = set()
    for file, root in _files([Path(p) for p in paths]):
        key = file.relative_to(root).as_posix()
        try:
            if key in seen:
                raise PageIndexError("duplicate document key in this run; index them separately or use a common directory")
            seen.add(key)
            if not file.is_file():
                raise PageIndexError("not a file")
            if file.stat().st_size > MAX_DOCUMENT_BYTES:
                raise PageIndexError(f"file exceeds {MAX_DOCUMENT_BYTES} bytes")
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                raise PageIndexError(f"cannot read as UTF-8 text: {type(exc).__name__}") from exc
            status = index_markdown_text(store, project, key, text, source_path=str(file))
            getattr(report, status).append(key)
        except PageIndexError as exc:
            report.failed[key if key else str(file)] = str(exc)
    return report
