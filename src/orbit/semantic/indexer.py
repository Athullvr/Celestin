"""Reconcile the vector index with the authoritative SQLite database.

SQLite and the vector file are separate stores, so writes are NOT atomic
across them. Recovery is reconciliation: ``sync`` compares every eligible
SQLite record with the index (project + content hash) and embeds only what is
missing or changed, then removes index entries whose source is gone or no
longer eligible. It is idempotent and resumable; re-running after a crash or
embedding outage picks up where the index is incomplete. SQLite is only read.

Eligibility mirrors retrieval policy: every chat message, and decisions with
status ``approved`` (drafts and deprecated decisions are never returned by
retrieval, so they are not embedded).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from .embeddings import EmbeddingError, EmbeddingProvider
from .vector_index import VectorIndex, VectorRecord

DEFAULT_SYNC_BATCH = 64

_TABLES = {
    "chat_message": ("chat_messages", "SELECT id, project, content, NULL AS key FROM chat_messages", ""),
    "canonical_decision": (
        "project_memory",
        "SELECT id, project, value AS content, key FROM project_memory",
        " AND status = 'approved'",
    ),
}


def embedding_text(kind: str, content: str, key: str | None = None) -> str:
    """Deterministic embedding input for a record."""
    if kind == "canonical_decision":
        return f"{key}\n{content}".strip()
    return content.strip()


def content_hash(model_id: str, text: str) -> str:
    return hashlib.sha256(f"{model_id}\x00{text}".encode("utf-8")).hexdigest()


@dataclass
class SyncReport:
    scanned: int = 0
    embedded: int = 0
    unchanged: int = 0
    removed_stale: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class Indexer:
    def __init__(
        self,
        connection: sqlite3.Connection,
        provider: EmbeddingProvider,
        index: VectorIndex,
        *,
        batch_size: int = DEFAULT_SYNC_BATCH,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._conn = connection
        self._provider = provider
        self._index = index
        self._batch = batch_size

    def _rows(self, kind: str, after_id: int):
        _, select, extra = _TABLES[kind]
        return self._conn.execute(
            f"{select} WHERE id > ?{extra} ORDER BY id LIMIT ?", (after_id, self._batch)
        ).fetchall()

    def _desired(self, kind: str, row) -> tuple[str, str]:
        text = embedding_text(kind, row["content"], row["key"])
        return text, content_hash(self._provider.model_id, text)

    def sync(self, *, dry_run: bool = False) -> SyncReport:
        """Index missing/changed records and drop stale ones.

        With ``dry_run`` nothing is embedded or written: ``embedded`` and
        ``removed_stale`` count what a real run would do.
        """
        report = SyncReport()
        for kind in _TABLES:
            try:
                self._sync_kind(kind, report, dry_run)
            except EmbeddingError as exc:
                report.error = f"embedding failed, index incomplete (re-run sync): {exc}"
                return report
            self._remove_stale(kind, report, dry_run)
        return report

    def _sync_kind(self, kind: str, report: SyncReport, dry_run: bool) -> None:
        last_id = 0
        while rows := self._rows(kind, last_id):
            last_id = rows[-1]["id"]
            present = self._index.entries(kind, [r["id"] for r in rows])
            todo = []
            for row in rows:
                report.scanned += 1
                if not row["content"].strip():
                    continue
                text, digest = self._desired(kind, row)
                if present.get(row["id"]) == (row["project"], digest):
                    report.unchanged += 1
                else:
                    todo.append((row, text, digest))
            if not todo:
                continue
            report.embedded += len(todo)
            if dry_run:
                continue
            vectors = self._provider.embed_documents([t for _, t, _ in todo])
            self._index.upsert(
                VectorRecord(kind, row["id"], row["project"], digest, vec)
                for (row, _, digest), vec in zip(todo, vectors)
            )

    def _remove_stale(self, kind: str, report: SyncReport, dry_run: bool) -> None:
        table, _, extra = _TABLES[kind]
        last_id = 0
        while ids := self._index.ids_after(kind, last_id, self._batch):
            last_id = ids[-1]
            marks = ",".join("?" * len(ids))
            live = {
                r[0]
                for r in self._conn.execute(
                    f"SELECT id FROM {table} WHERE id IN ({marks}){extra}", ids
                )
            }
            for record_id in ids:
                if record_id not in live:
                    report.removed_stale += 1
                    if not dry_run:
                        self._index.delete(kind, record_id)

    def index_record(self, kind: str, record_id: int) -> None:
        """Index (or remove) one record; used for best-effort incremental updates."""
        table, select, extra = _TABLES[kind]
        row = self._conn.execute(
            f"{select} WHERE id = ?{extra}", (record_id,)
        ).fetchone()
        if row is None or not row["content"].strip():
            self._index.delete(kind, record_id)
            return
        text, digest = self._desired(kind, row)
        (vector,) = self._provider.embed_documents([text])
        self._index.upsert([VectorRecord(kind, record_id, row["project"], digest, vector)])
