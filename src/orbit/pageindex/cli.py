"""``celestin-docs``: index Markdown documents for PageIndex-style retrieval.

Only the separate document-index file is written; the SQLite database is untouched.
"""

from __future__ import annotations

import argparse
import sys

from .backend import PageIndexBackend, route
from .config import build_pageindex_backend, load_settings
from .errors import PageIndexError, PageIndexUnavailable
from .indexer import index_paths, rebuild_project
from .store import PageIndexStore


def _embed_sections(settings) -> None:
    """Keep section embeddings in step when semantic search is enabled (best effort)."""
    from orbit.semantic.config import sync_sections_after_index

    status = sync_sections_after_index()
    if status:
        print(status)


def _index(args, settings) -> int:
    with PageIndexStore(settings.store_path) as store:
        report = index_paths(store, args.project, args.paths)
    for label in ("added", "updated", "unchanged"):
        for key in getattr(report, label):
            print(f"{label}: {key}")
    for key, reason in report.failed.items():
        print(f"FAILED: {key}: {reason}", file=sys.stderr)
    if report.added or report.updated:
        _embed_sections(settings)
    if not (report.added or report.updated or report.unchanged or report.failed):
        print("no Markdown files found", file=sys.stderr)
        return 1
    return 0 if report.ok else 1


def _status(args, settings) -> int:
    try:
        with PageIndexStore(settings.store_path, create=False) as store:
            docs = store.documents(args.project)
    except PageIndexUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    with PageIndexStore(settings.store_path, create=False) as store:
        missing = set(store.missing_sources(args.project))
    print(f"document index: {settings.store_path}")
    for d in docs:
        flag = "  MISSING SOURCE (see: celestin-docs prune)" if d.doc_key in missing else ""
        print(f"{d.doc_key}  sections={d.sections}  indexed={d.indexed_at}  sha256={d.content_hash[:12]}{flag}")
    print(f"{len(docs)} document(s) in project {args.project!r}")
    return 0


def _remove(args, settings) -> int:
    with PageIndexStore(settings.store_path, create=False) as store:
        removed = store.remove_document(args.project, args.doc_key)
    print("removed" if removed else "not found")
    if removed:
        _embed_sections(settings)
    return 0 if removed else 1


def _prune(args, settings) -> int:
    with PageIndexStore(settings.store_path, create=False) as store:
        missing = store.missing_sources(args.project)
        for key in missing:
            if args.yes:
                store.remove_document(args.project, key)
            print(f"{'removed' if args.yes else 'would remove'}: {key}")
    if missing and args.yes:
        _embed_sections(settings)
    if missing and not args.yes:
        print("re-run with --yes to remove them from the index (source files are never touched)")
    if not missing:
        print("no documents with missing sources")
    return 0


def _rebuild(args, settings) -> int:
    with PageIndexStore(settings.store_path, create=False) as store:
        report = rebuild_project(store, args.project)
    with PageIndexStore(settings.store_path, create=False) as store:
        store.rebuild_section_index()
    for key in report.updated:
        print(f"rebuilt: {key}")
    _embed_sections(settings)
    for key, reason in report.failed.items():
        print(f"FAILED: {key}: {reason}", file=sys.stderr)
    return 0 if report.ok else 1


def _search(args, settings) -> int:
    skip = route(args.query)
    if skip:
        print(f"note: PageIndex would be skipped in retrieve_context ({skip}); running anyway")
    backend: PageIndexBackend | None = build_pageindex_backend()
    if backend is None:
        print("ERROR: set CELESTIN_PAGEINDEX=1 and CELESTIN_PAGEINDEX_MODEL to search", file=sys.stderr)
        return 1
    try:
        sections = backend.retrieve(args.project, args.query)
    except PageIndexUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for s in sections or []:
        print(f"{s.doc_key} :: {' > '.join(s.path)} (line {s.line_num}, node {s.node_id})")
    if not sections:
        print("no sections selected" if sections is not None else "no documents indexed for this project")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="celestin-docs", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("index", help="index Markdown files or directories (idempotent; changed files are re-indexed)")
    p.add_argument("--project", required=True)
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("status", help="list indexed documents")
    p.add_argument("--project", required=True)
    p = sub.add_parser("remove", help="remove one document from the index")
    p.add_argument("--project", required=True)
    p.add_argument("doc_key")
    p = sub.add_parser("prune", help="remove documents whose source file is gone (dry run unless --yes)")
    p.add_argument("--project", required=True)
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("rebuild", help="re-derive all trees from the stored original text")
    p.add_argument("--project", required=True)
    p = sub.add_parser("search", help="ask the navigation model which sections answer a query (needs a model)")
    p.add_argument("--project", required=True)
    p.add_argument("query")
    args = parser.parse_args(argv)
    handlers = {"index": _index, "status": _status, "remove": _remove, "search": _search,
                "prune": _prune, "rebuild": _rebuild}
    try:
        return handlers[args.command](args, load_settings())
    except (PageIndexError, PageIndexUnavailable, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
