"""Derived vector index stored in a separate SQLite file using sqlite-vec.

The index never holds message or decision content: only a stable reference
(``kind`` + SQLite row id), the project, a content hash and the vector. It can
be deleted or rebuilt from the authoritative database at any time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .embeddings import validate_vector

KINDS = ("chat_message", "canonical_decision")
SCHEMA_VERSION = "1"


class VectorIndexError(RuntimeError):
    """The vector index is missing, unreadable, or inconsistent."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    kind: str
    record_id: int
    project: str
    content_hash: str
    vector: Sequence[float]


@dataclass(frozen=True, slots=True)
class VectorHit:
    kind: str
    record_id: int
    project: str
    similarity: float


def _rowid(kind: str, record_id: int) -> int:
    # Messages and decisions have independent id spaces; interleave them.
    return record_id * 2 + (0 if kind == "chat_message" else 1)


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise VectorIndexError(f"unknown record kind {kind!r}")
    return kind


class VectorIndex:
    def __init__(
        self,
        path: str | Path,
        *,
        model_id: str,
        dimension: int,
        create: bool = True,
        check_compat: bool = True,
    ) -> None:
        self._path = Path(path)
        self._model_id = model_id
        self._dimension = dimension
        if not create and not self._path.exists():
            raise VectorIndexError(
                f"vector index not found at {self._path}; run: celestin-index sync"
            )
        try:
            import sqlite_vec
        except ImportError as exc:
            raise VectorIndexError(
                "sqlite-vec is not installed; run: pip install 'celestin-memory[semantic]'"
            ) from exc
        if create:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._path), isolation_level=None)
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._serialize = sqlite_vec.serialize_float32
            self._open_schema(create, check_compat)
        except (sqlite3.Error, AttributeError) as exc:
            raise VectorIndexError(f"cannot open vector index {self._path}: {exc}") from exc

    def _open_schema(self, create: bool, check_compat: bool) -> None:
        has_info = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'index_info'"
        ).fetchone()
        if not has_info:
            if not create:
                raise VectorIndexError("vector index is empty; run: celestin-index sync")
            self._create_tables()
            return
        info = dict(self._conn.execute("SELECT key, value FROM index_info"))
        if check_compat and (
            info.get("model_id") != self._model_id
            or info.get("dimension") != str(self._dimension)
            or info.get("schema_version") != SCHEMA_VERSION
        ):
            raise VectorIndexError(
                f"vector index was built with model {info.get('model_id')!r} "
                f"({info.get('dimension')} dims); run: celestin-index rebuild"
            )

    def _create_tables(self) -> None:
        self._conn.executescript(
            f"""
            CREATE TABLE index_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE vector_meta (
                rowid        INTEGER PRIMARY KEY,
                kind         TEXT NOT NULL,
                record_id    INTEGER NOT NULL,
                project      TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                UNIQUE (kind, record_id)
            );
            CREATE VIRTUAL TABLE vectors USING vec0(
                project TEXT PARTITION KEY,
                kind TEXT,
                embedding FLOAT[{int(self._dimension)}] DISTANCE_METRIC=cosine
            );
            """
        )
        self._conn.executemany(
            "INSERT INTO index_info VALUES (?, ?)",
            [
                ("model_id", self._model_id),
                ("dimension", str(self._dimension)),
                ("schema_version", SCHEMA_VERSION),
            ],
        )

    def _rollback(self) -> None:
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "VectorIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert(self, records: Iterable[VectorRecord]) -> int:
        """Insert or replace records in one transaction; idempotent."""
        prepared = []
        for r in records:
            _check_kind(r.kind)
            if not r.project or not r.content_hash:
                raise VectorIndexError("project and content_hash are required")
            prepared.append((r, self._serialize(validate_vector(r.vector, self._dimension))))
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            for r, blob in prepared:
                rowid = _rowid(r.kind, r.record_id)
                self._conn.execute("DELETE FROM vectors WHERE rowid = ?", (rowid,))
                self._conn.execute(
                    "INSERT INTO vectors(rowid, project, kind, embedding) VALUES (?, ?, ?, ?)",
                    (rowid, r.project, r.kind, blob),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO vector_meta VALUES (?, ?, ?, ?, ?)",
                    (rowid, r.kind, r.record_id, r.project, r.content_hash),
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._rollback()
            raise VectorIndexError(f"vector upsert failed: {exc}") from exc
        return len(prepared)

    def delete(self, kind: str, record_id: int) -> None:
        rowid = _rowid(_check_kind(kind), record_id)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute("DELETE FROM vectors WHERE rowid = ?", (rowid,))
            self._conn.execute("DELETE FROM vector_meta WHERE rowid = ?", (rowid,))
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._rollback()
            raise VectorIndexError(f"vector delete failed: {exc}") from exc

    def search(
        self, query_vector: Sequence[float], *, project: str, kind: str, limit: int
    ) -> list[VectorHit]:
        """Nearest neighbours within ``project`` and ``kind`` (filtered inside the KNN query)."""
        _check_kind(kind)
        if limit < 1:
            raise VectorIndexError("limit must be at least 1")
        blob = self._serialize(validate_vector(query_vector, self._dimension))
        try:
            rows = self._conn.execute(
                "SELECT v.rowid, v.distance, m.kind, m.record_id, m.project "
                "FROM vectors v JOIN vector_meta m ON m.rowid = v.rowid "
                "WHERE v.embedding MATCH ? AND k = ? AND v.project = ? AND v.kind = ? "
                "ORDER BY v.distance ASC, m.record_id ASC",
                (blob, limit, project, kind),
            ).fetchall()
        except sqlite3.Error as exc:
            raise VectorIndexError(f"vector search failed: {exc}") from exc
        # Re-check project/kind from the metadata table, not only the KNN filter.
        return [
            VectorHit(k, int(rid), p, 1.0 - float(dist))
            for _, dist, k, rid, p in rows
            if p == project and k == kind
        ]

    def entries(self, kind: str, record_ids: Sequence[int]) -> dict[int, tuple[str, str]]:
        """Return ``{record_id: (project, content_hash)}`` for the ids present."""
        if not record_ids:
            return {}
        marks = ",".join("?" * len(record_ids))
        rows = self._conn.execute(
            f"SELECT record_id, project, content_hash FROM vector_meta "
            f"WHERE kind = ? AND record_id IN ({marks})",
            (_check_kind(kind), *record_ids),
        )
        return {int(r[0]): (r[1], r[2]) for r in rows}

    def ids_after(self, kind: str, after_id: int, limit: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT record_id FROM vector_meta WHERE kind = ? AND record_id > ? "
            "ORDER BY record_id LIMIT ?",
            (_check_kind(kind), after_id, limit),
        )
        return [int(r[0]) for r in rows]

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return int(self._conn.execute("SELECT COUNT(*) FROM vector_meta").fetchone()[0])
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM vector_meta WHERE kind = ?", (_check_kind(kind),)
            ).fetchone()[0]
        )

    def health_check(self, *, deep: bool = False) -> list[str]:
        """Return a list of detected problems (empty when healthy)."""
        problems = []
        try:
            meta = self.count()
            vecs = int(self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])
            if meta != vecs:
                problems.append(f"metadata rows ({meta}) and vectors ({vecs}) disagree")
            orphan = self._conn.execute(
                "SELECT COUNT(*) FROM vector_meta WHERE rowid NOT IN (SELECT rowid FROM vectors)"
            ).fetchone()[0]
            if orphan:
                problems.append(f"{orphan} metadata rows have no vector")
            check = self._conn.execute("PRAGMA quick_check").fetchone()[0] if deep else "ok"
            if check != "ok":
                problems.append(f"sqlite integrity check failed: {check}")
        except sqlite3.Error as exc:
            problems.append(f"index unreadable: {exc}")
        return problems

    def reset(self) -> None:
        """Drop all derived data and recreate empty tables (the rebuild step)."""
        try:
            self._conn.executescript(
                "DROP TABLE IF EXISTS vectors; DROP TABLE IF EXISTS vector_meta; "
                "DROP TABLE IF EXISTS index_info;"
            )
            self._create_tables()
        except sqlite3.Error as exc:
            raise VectorIndexError(f"vector index reset failed: {exc}") from exc
