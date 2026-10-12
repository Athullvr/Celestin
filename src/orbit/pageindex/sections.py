"""Heading-section keyword search over the document store (FTS5, no model)."""

from __future__ import annotations

import sqlite3

from .errors import PageIndexUnavailable
from .store import PageIndexStore, StoredSection


def search_sections(
    store: PageIndexStore, project: str, query: str, limit: int, *, relax: bool = True
) -> tuple[list[StoredSection], str]:
    """Best-first sections of ``project`` for ``query`` and the FTS tier that produced them.

    Uses the same strict-then-bounded-relaxed tiers as chat search. Project filtering happens in
    the SQL join, so sections of other projects can never be returned.
    """
    from orbit.retrieval.fts import tiered_match  # imported here: orbit.retrieval imports this package

    if not store.has_section_index():
        raise PageIndexUnavailable("section index missing; run: celestin-docs rebuild")
    conn = store.connection()

    def run(match: str, row_limit: int) -> list[StoredSection]:
        try:
            rows = conn.execute(
                "SELECT s.rowid FROM sections_fts f "
                "JOIN sections s ON s.rowid = f.rowid JOIN documents d ON d.id = s.doc_id "
                "WHERE sections_fts MATCH ? AND d.project = ? "
                "ORDER BY bm25(sections_fts), d.doc_key, s.line_num LIMIT ?",
                (match, project, row_limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PageIndexUnavailable(f"section search failed: {exc}") from exc
        found = store.by_row_ids(project, [r[0] for r in rows])
        return [found[r[0]] for r in rows if r[0] in found]

    return tiered_match(run, query, limit, relax, content_of=lambda sec: sec.text)
