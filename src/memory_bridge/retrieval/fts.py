"""SQLite FTS5 message search behind an explicitly configured schema adapter."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_FTS5_VIRTUAL_TABLE = re.compile(
    r"^\s*create\s+virtual\s+table\b[^()]*\busing\s+fts5\s*\(",
    re.IGNORECASE,
)


class SearchIndexUnavailable(RuntimeError):
    """Raised when the configured FTS5 table cannot be queried."""


@dataclass(frozen=True, slots=True)
class FtsSchema:
    """Names required to map a message FTS table to retrieval results.

    This is an adapter configuration, not a database schema declaration. The
    table and columns must already exist; this class never creates or changes
    database objects.
    """

    table: str
    message_id: str
    project_id: str
    source_id: str
    created_at: str
    content: str

    def __post_init__(self) -> None:
        for name in (
            self.table,
            self.message_id,
            self.project_id,
            self.source_id,
            self.created_at,
            self.content,
        ):
            if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
                raise ValueError(f"Invalid SQLite identifier: {name!r}")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Traceable message match; lower relevance_score means a better match."""

    message_id: str
    project_id: str
    source_id: str
    content: str
    timestamp: str | None
    relevance_score: float


def _fts_terms(query: str) -> str:
    terms = _WORD.findall(query)
    if not terms:
        return ""
    return " AND ".join(f'"{term}"' for term in terms)


class FtsMessageSearch:
    """Search an existing FTS5 message table without managing its lifecycle."""

    def __init__(self, connection: sqlite3.Connection, schema: FtsSchema) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self._connection = connection
        self._schema = schema

    def search(
        self,
        query: str,
        *,
        project_id: str,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Return project-scoped FTS matches, ordered by BM25 then recency.

        Query text is treated as plain terms joined with AND. FTS operators and
        punctuation are not exposed as query syntax. Empty or punctuation-only
        queries return an empty list without touching the database.
        """
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if "\x00" in query:
            raise ValueError("query must not contain NUL characters")
        if not isinstance(project_id, str):
            raise TypeError("project_id must be a string")
        if not project_id.strip() or "\x00" in project_id:
            raise ValueError("project_id must be non-empty and contain no NUL characters")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        match_query = _fts_terms(query)
        if not match_query:
            return []

        schema = self._schema
        table = f'"{schema.table}"'
        fields = ", ".join(
            f'"{name}"'
            for name in (
                schema.message_id,
                schema.project_id,
                schema.source_id,
                schema.created_at,
                schema.content,
            )
        )
        sql = (
            f"SELECT {fields}, bm25({table}) "
            f'FROM {table} WHERE "{schema.content}" MATCH ? '
            f'AND "{schema.project_id}" = ? '
            f'ORDER BY 6 ASC, julianday("{schema.created_at}") DESC, 1 ASC, 3 ASC LIMIT ?'
        )
        try:
            table_row = self._connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (schema.table,),
            ).fetchone()
            if table_row is None or not isinstance(table_row[0], str) or not _FTS5_VIRTUAL_TABLE.search(table_row[0]):
                raise SearchIndexUnavailable(
                    f"Configured FTS5 table {schema.table!r} is missing or incompatible"
                )
            table_columns = {
                row[1]
                for row in self._connection.execute(
                    f'PRAGMA table_info("{schema.table}")'
                )
            }
            required_columns = {
                schema.message_id,
                schema.project_id,
                schema.source_id,
                schema.created_at,
                schema.content,
            }
            if not required_columns.issubset(table_columns):
                raise SearchIndexUnavailable(
                    f"Configured FTS5 table {schema.table!r} is missing or incompatible"
                )
            rows = self._connection.execute(sql, (match_query, project_id, limit))
            return [
                SearchResult(
                    message_id=row[0],
                    project_id=row[1],
                    source_id=row[2],
                    timestamp=row[3],
                    content=row[4],
                    relevance_score=float(row[5]),
                )
                for row in rows
            ]
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "no such table" in message or "no such column" in message or "match" in message:
                raise SearchIndexUnavailable(
                    f"Configured FTS5 table {schema.table!r} is missing or incompatible"
                ) from exc
            raise
