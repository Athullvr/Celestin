"""Rebuildable SQLite store for document section trees (separate from the main database)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .errors import PageIndexUnavailable
from .tree import Section

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY,
    project      TEXT NOT NULL,
    doc_key      TEXT NOT NULL,
    source_path  TEXT,
    content_hash TEXT NOT NULL,
    tree_schema  TEXT NOT NULL,
    title        TEXT NOT NULL,
    source_text  TEXT NOT NULL,
    indexed_at   TEXT NOT NULL,
    UNIQUE (project, doc_key)
);
CREATE TABLE IF NOT EXISTS sections (
    doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    node_id   TEXT NOT NULL,
    parent_id TEXT,
    title     TEXT NOT NULL,
    path_json TEXT NOT NULL,
    level     INTEGER NOT NULL,
    line_num  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (doc_id, node_id)
);
-- Heading-section keyword index. External content: the text stays in `sections` only.
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    path_json, text, content='sections', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS sections_fts_insert AFTER INSERT ON sections BEGIN
    INSERT INTO sections_fts(rowid, path_json, text) VALUES (new.rowid, new.path_json, new.text);
END;
CREATE TRIGGER IF NOT EXISTS sections_fts_delete AFTER DELETE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, path_json, text)
    VALUES ('delete', old.rowid, old.path_json, old.text);
END;
"""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredSection:
    project: str
    doc_key: str
    source_path: str | None
    content_hash: str
    indexed_at: str
    node_id: str
    title: str
    path: tuple[str, ...]
    line_num: int
    text: str
    row_id: int = 0


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    doc_key: str
    source_path: str | None
    content_hash: str
    tree_schema: str
    title: str
    indexed_at: str
    sections: int


class PageIndexStore:
    def __init__(self, path: str | Path, *, create: bool = True) -> None:
        self._path = Path(path)
        if not create and not self._path.exists():
            raise PageIndexUnavailable(
                f"document index not found at {self._path}; run: celestin-docs index"
            )
        if create:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._path), isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            if create:
                self._conn.execute("PRAGMA journal_mode = WAL")
                had_fts = self._has_table("sections_fts")
                self._conn.executescript(SCHEMA)
                if not had_fts and self._has_table("documents"):
                    self.rebuild_section_index()  # stores created before heading-section search
            else:
                self._conn.execute("SELECT 1 FROM documents LIMIT 1")
        except sqlite3.Error as exc:
            raise PageIndexUnavailable(f"cannot open document index {self._path}: {exc}") from exc

    def _has_table(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None

    def rebuild_section_index(self) -> None:
        """Re-derive the keyword index from `sections` (the derived index is always rebuildable)."""
        self._conn.execute("INSERT INTO sections_fts(sections_fts) VALUES ('rebuild')")

    def has_section_index(self) -> bool:
        return self._has_table("sections_fts")

    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PageIndexStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert_document(
        self,
        project: str,
        doc_key: str,
        source_path: str | None,
        source_text: str,
        title: str,
        sections: Sequence[Section],
        tree_schema: str,
        *,
        force: bool = False,
    ) -> str:
        """Insert or replace one document atomically. Returns added|updated|unchanged."""
        digest = content_hash(source_text)
        row = self._conn.execute(
            "SELECT id, content_hash, tree_schema FROM documents WHERE project = ? AND doc_key = ?",
            (project, doc_key),
        ).fetchone()
        if not force and row and row["content_hash"] == digest and row["tree_schema"] == tree_schema:
            return "unchanged"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if row:
                self._conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
            doc_id = self._conn.execute(
                "INSERT INTO documents (project, doc_key, source_path, content_hash, tree_schema, "
                "title, source_text, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, doc_key, source_path, digest, tree_schema, title, source_text, now),
            ).lastrowid
            self._conn.executemany(
                "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (doc_id, s.node_id, s.parent_id, s.title, json.dumps(s.path), s.level, s.line_num, s.text)
                    for s in sections
                ],
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return "updated" if row else "added"

    def remove_document(self, project: str, doc_key: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM documents WHERE project = ? AND doc_key = ?", (project, doc_key)
        )
        return cur.rowcount > 0

    def documents(self, project: str) -> list[DocumentInfo]:
        rows = self._conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM sections s WHERE s.doc_id = d.id) AS n "
            "FROM documents d WHERE d.project = ? ORDER BY d.doc_key",
            (project,),
        )
        return [
            DocumentInfo(r["doc_key"], r["source_path"], r["content_hash"], r["tree_schema"],
                         r["title"], r["indexed_at"], r["n"])
            for r in rows
        ]

    def sections(self, project: str) -> list[StoredSection]:
        """Every section of the project's documents, in document then outline order."""
        return self._query(
            "WHERE d.project = ? ORDER BY d.doc_key, s.line_num, s.node_id", (project,)
        )

    def by_row_ids(self, project: str, row_ids: Sequence[int]) -> dict[int, StoredSection]:
        """Sections by internal id, re-filtered by project (stale or foreign ids are simply absent)."""
        if not row_ids:
            return {}
        marks = ",".join("?" * len(row_ids))
        found = self._query(f"WHERE d.project = ? AND s.rowid IN ({marks})", (project, *row_ids))
        return {s.row_id: s for s in found}

    def get(self, project: str, doc_key: str, node_id: str) -> StoredSection | None:
        found = self._query(
            "WHERE d.project = ? AND d.doc_key = ? AND s.node_id = ?", (project, doc_key, node_id)
        )
        return found[0] if found else None

    def fingerprint(self, project: str) -> str:
        """Changes whenever any indexed document of the project is added, replaced or removed."""
        rows = self._conn.execute(
            "SELECT doc_key, content_hash, tree_schema FROM documents WHERE project = ? ORDER BY doc_key",
            (project,),
        ).fetchall()
        return hashlib.sha256(json.dumps([tuple(r) for r in rows]).encode()).hexdigest()

    def missing_sources(self, project: str) -> list[str]:
        """doc_keys whose recorded source file no longer exists (never deleted implicitly)."""
        rows = self._conn.execute(
            "SELECT doc_key, source_path FROM documents WHERE project = ? AND source_path IS NOT NULL ORDER BY doc_key",
            (project,),
        )
        return [r["doc_key"] for r in rows if not Path(r["source_path"]).exists()]

    def source_path(self, project: str, doc_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT source_path FROM documents WHERE project = ? AND doc_key = ?", (project, doc_key)
        ).fetchone()
        return row[0] if row else None

    def source_text(self, project: str, doc_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT source_text FROM documents WHERE project = ? AND doc_key = ?", (project, doc_key)
        ).fetchone()
        return row[0] if row else None

    def _query(self, tail: str, params: tuple) -> list[StoredSection]:
        rows = self._conn.execute(
            "SELECT d.project, d.doc_key, d.source_path, d.content_hash, d.indexed_at, "
            "s.node_id, s.title, s.path_json, s.line_num, s.text, s.rowid AS row_id "
            f"FROM sections s JOIN documents d ON d.id = s.doc_id {tail}",
            params,
        )
        return [
            StoredSection(r["project"], r["doc_key"], r["source_path"], r["content_hash"],
                          r["indexed_at"], r["node_id"], r["title"], tuple(json.loads(r["path_json"])),
                          r["line_num"], r["text"], r["row_id"])
            for r in rows
        ]
