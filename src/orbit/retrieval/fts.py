"""SQLite FTS5 message search behind an explicitly configured schema adapter."""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_FTS5_VIRTUAL_TABLE = re.compile(
    r"^\s*create\s+virtual\s+table\b[^()]*\busing\s+fts5\s*\(",
    re.IGNORECASE,
)


_QUOTED = re.compile(r'"([^"]+)"')
_STOPWORDS = frozenset(
    "a an the of to in on for and or is are was were be been being how what which who whom whose why "
    "when where does do did can could may might must should would will shall by with from that this "
    "these those it its as at after before over under between about into than then there their they "
    "we our us you your i me my he she his her not no if so but also just".split()
)
# Terms that look like identifiers (error codes, versions, paths, snake_case) must keep matching exactly.
_IDENTIFIER_LIKE = re.compile(r"[0-9_]|\.\w|\w[/\\]\w")
MIN_RELAXED_TERMS = 3
RELAXED_MATCH_RATIO = 0.6
RELAXED_POOL_FACTOR = 5


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
    role: str | None = None


def _fts_terms(query: str) -> str:
    """Strict query: every word (and every "quoted phrase") must match."""
    phrases = [_WORD.findall(p) for p in _QUOTED.findall(query)]
    terms = _WORD.findall(_QUOTED.sub(" ", query))
    parts = [f'"{" ".join(words)}"' for words in phrases if words]
    parts += [f'"{term}"' for term in terms]
    return " AND ".join(parts)


def _relaxed_plan(query: str) -> tuple[str, list[str], int] | None:
    """Plan for the OR fallback, or None when the query is too short to relax safely.

    Returns (match query, content terms, minimum terms a result must contain).
    Identifier-like raw tokens (``ERR_4471``, ``v1.2``, ``src/app.py``) are required
    to match, so relaxation never loosens an exact lookup.
    """
    raw = [t for t in re.findall(r"\S+", _QUOTED.sub(lambda m: m.group(1), query))]
    required: list[str] = []
    optional: list[str] = []
    for token in raw:
        words = _WORD.findall(token)
        if not words:
            continue
        if _IDENTIFIER_LIKE.search(token):
            required += [w for w in words if w not in required]
        else:
            optional += [w for w in words if w.casefold() not in _STOPWORDS and w not in optional and w not in required]
    content = required + optional
    if len(content) < MIN_RELAXED_TERMS or not optional:
        return None
    min_match = max(len(required) + 1, math.ceil(len(content) * RELAXED_MATCH_RATIO))
    optional_expr = "(" + " OR ".join(f'"{w}"' for w in optional) + ")"
    required_expr = " AND ".join(f'"{w}"' for w in required)
    return (f"{required_expr} AND {optional_expr}" if required else optional_expr), content, min_match


def _without_stopwords(query: str) -> str:
    """Strict AND over the non-stopword terms, or "" when nothing would change."""
    terms = _WORD.findall(_QUOTED.sub(lambda m: m.group(1), query))
    kept = [t for t in terms if t.casefold() not in _STOPWORDS]
    if not kept or len(kept) == len(terms):
        return ""
    return " AND ".join(f'"{t}"' for t in kept)


def tiered_match(run, query: str, limit: int, relax: bool, content_of=lambda r: r.content):
    """Run strict then (if ``relax``) bounded relaxed FTS5 queries; return (results, tier).

    ``run(match_expression, row_limit)`` executes one MATCH and returns ordered results.
    Shared by message, decision and document-section search so all use the same tiers.
    """
    strict = _fts_terms(query)
    if not strict:
        return [], "strict"
    results = run(strict, limit)
    if results or not relax:
        return results, "strict"
    stopless = _without_stopwords(query)
    if stopless:
        results = run(stopless, limit)
        if results:
            return results, "no_stopwords"
    plan = _relaxed_plan(query)
    if plan is None:
        return [], "strict"
    relaxed_query, terms, min_match = plan
    wanted = [t.casefold() for t in terms]
    kept = []
    for result in run(relaxed_query, limit * RELAXED_POOL_FACTOR):
        words = {w.casefold() for w in _WORD.findall(content_of(result))}
        if sum(t in words for t in wanted) >= min_match:
            kept.append(result)
    return (kept[:limit], "relaxed_or") if kept else ([], "strict")


class FtsMessageSearch:
    """Search an existing FTS5 message table without managing its lifecycle."""

    def __init__(self, connection: sqlite3.Connection, schema: FtsSchema) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self._connection = connection
        self._schema = schema
        self.last_tier = "strict"

    def search(
        self,
        query: str,
        *,
        project_id: str,
        limit: int = 10,
        relax: bool = False,
    ) -> list[SearchResult]:
        """Return project-scoped FTS matches, ordered by BM25 then recency.

        Query text is treated as plain terms joined with AND (a ``"quoted phrase"``
        must match adjacently). FTS operators and punctuation are not exposed as
        query syntax. Empty or punctuation-only queries return an empty list
        without touching the database.

        With ``relax=True``, a query whose strict form finds nothing is retried in
        bounded steps, and the first step with results wins (``last_tier`` records
        which): 1) strict AND without stopwords; 2) for queries with at least
        three content terms, an OR query where a result must contain at least 60%
        of the terms plus every identifier-like term. Queries that match strictly
        are never changed.
        """
        self.last_tier = "strict"
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
        self.last_tier = "strict"

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
            def run(match: str, row_limit: int) -> list[SearchResult]:
                rows = self._connection.execute(sql, (match, project_id, row_limit))
                return [
                    SearchResult(
                        message_id=str(row[0]),
                        project_id=str(row[1]),
                        source_id=str(row[2]),
                        timestamp=str(row[3]) if row[3] is not None else None,
                        content=str(row[4]),
                        relevance_score=float(row[5]),
                    )
                    for row in rows
                ]

            results, self.last_tier = tiered_match(run, query, limit, relax)
            return results
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "no such table" in message or "no such column" in message or "match" in message:
                raise SearchIndexUnavailable(
                    f"Configured FTS5 table {schema.table!r} is missing or incompatible"
                ) from exc
            raise
