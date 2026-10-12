"""``celestin-index``: build, inspect and repair the semantic vector index.

Only the derived vector file is ever written; the SQLite database is read-only here.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import closing

from orbit.database.engine import connect

from .config import get_provider, load_settings
from .embeddings import EmbeddingError
from .indexer import Indexer
from .vector_index import VectorIndex, VectorIndexError
from orbit.pageindex.config import load_settings as load_pageindex_settings
from orbit.pageindex.store import PageIndexStore


def _open_index(settings, provider, *, check_compat: bool = True, create: bool = True) -> VectorIndex:
    return VectorIndex(
        settings.vector_path,
        model_id=provider.model_id,
        dimension=provider.dimension,
        create=create,
        check_compat=check_compat,
    )


def _print_report(label: str, report) -> int:
    print(
        f"{label}: scanned={report.scanned} embedded={report.embedded} "
        f"unchanged={report.unchanged} removed_stale={report.removed_stale}"
    )
    if report.error:
        print(f"ERROR: {report.error}", file=sys.stderr)
        return 1
    return 0


def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        provider = get_provider(settings)
    except EmbeddingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"vector index: {settings.vector_path} (model {provider.model_id}, {provider.dimension} dims)")
    with closing(connect()) as conn:
        if args.command == "rebuild":
            # The index is derived data: reset it, discarding a stale or corrupt file.
            try:
                with _open_index(settings, provider, check_compat=False) as index:
                    index.reset()
            except VectorIndexError:
                settings.vector_path.unlink(missing_ok=True)
        try:
            index_cm = _open_index(settings, provider, create=args.command != "status")
        except VectorIndexError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        # Heading sections live in the optional document store; index them when it exists.
        doc_path = load_pageindex_settings().store_path
        doc_store = PageIndexStore(doc_path, create=False) if doc_path.exists() else None
        with index_cm as index:
            indexer = Indexer(
                conn, provider, index, batch_size=args.batch_size,
                sections_connection=doc_store.connection() if doc_store else None,
            )
            if args.command == "status":
                plan = indexer.sync(dry_run=True)
                code = _print_report("plan (dry run)", plan)
                if plan.embedded or plan.removed_stale:
                    print("index is out of date; run: celestin-index sync")
                    code = 1
                problems = index.health_check(deep=True)
                for problem in problems:
                    print(f"PROBLEM: {problem}")
                print(f"indexed: {index.count()} records")
                return code or (1 if problems else 0)
            try:
                return _print_report(args.command, indexer.sync())
            finally:
                if doc_store:
                    doc_store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="celestin-index", description=__doc__)
    parser.add_argument("command", choices=["sync", "rebuild", "status"],
                        help="sync: index missing/changed records; rebuild: reset then sync; "
                             "status: dry-run report and integrity check")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (VectorIndexError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
