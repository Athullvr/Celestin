"""SQLite implementation of the retrieval data port."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from orbit.repositories.decisions import DecisionRepository
from orbit.retrieval.data import (
    DecisionRecord,
    MessageRecord,
    RetrievalData,
    SearchMatch,
    SearchPage,
)
from orbit.retrieval.fts import FtsMessageSearch, FtsSchema

MESSAGE_FTS_SCHEMA = FtsSchema(
    table="chat_messages_fts",
    message_id="message_id",
    project_id="project_id",
    source_id="source_id",
    created_at="created_at",
    content="content",
)

DECISION_FTS_SCHEMA = FtsSchema(
    table="project_memory_fts",
    message_id="decision_id",
    project_id="project_id",
    source_id="source_id",
    created_at="updated_at",
    content="value",
)


class SQLiteRetrievalData(RetrievalData):
    """Keep FTS5 queries, SQLite rows, and repository reads behind a small port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self._connection = connection
        self._message_search = FtsMessageSearch(connection, MESSAGE_FTS_SCHEMA)
        self._decision_search = FtsMessageSearch(connection, DECISION_FTS_SCHEMA)
        self._decisions = DecisionRepository(connection)

    def search_messages(
        self, project: str, query: str, limit: int, *, relax: bool
    ) -> SearchPage:
        results = self._message_search.search(
            query, project_id=project, limit=limit, relax=relax
        )
        records = self.load_messages(project, [result.message_id for result in results])
        return SearchPage(
            tuple(
                SearchMatch(
                    record_id=result.message_id,
                    project=records[result.message_id].project,
                    content=records[result.message_id].content,
                    timestamp=records[result.message_id].created_at,
                    source_id=records[result.message_id].conversation_id,
                    score=result.relevance_score,
                    role=records[result.message_id].role,
                )
                for result in results
                if result.message_id in records
            ),
            self._message_search.last_tier,
        )

    def search_decisions(
        self, project: str, query: str, limit: int, *, relax: bool
    ) -> SearchPage:
        results = self._decision_search.search(
            query, project_id=project, limit=limit, relax=relax
        )
        records = self.load_decisions(project, [result.message_id for result in results])
        # Preserve FTS order and omit stale index entries exactly as before.
        matches = tuple(
            SearchMatch(
                record_id=result.message_id,
                project=records[result.message_id].project,
                content=records[result.message_id].value,
                timestamp=records[result.message_id].updated_at,
                source_id=records[result.message_id].source_message_id,
                score=result.relevance_score,
                status=records[result.message_id].status,
            )
            for result in results
            if result.message_id in records
        )
        return SearchPage(matches, self._decision_search.last_tier)

    def load_messages(
        self, project: str, message_ids: Sequence[str]
    ) -> dict[str, MessageRecord]:
        ids = _sqlite_ids(message_ids)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"SELECT id, project, conversation_id, content, created_at, role "
            f"FROM chat_messages WHERE project = ? AND id IN ({marks})",
            (project, *ids),
        )
        return {
            str(row["id"]): MessageRecord(
                message_id=str(row["id"]),
                project=row["project"],
                conversation_id=row["conversation_id"],
                content=row["content"],
                created_at=row["created_at"],
                role=row["role"],
            )
            for row in rows
        }

    def load_decisions(
        self, project: str, decision_ids: Sequence[str]
    ) -> dict[str, DecisionRecord]:
        wanted = {str(value) for value in _sqlite_ids(decision_ids)}
        if not wanted:
            return {}
        # DecisionRepository applies the authoritative project filter and includes
        # all statuses; shared ranking, not this adapter, owns eligibility policy.
        rows = self._decisions.list_for_project(project, include_deprecated=True)
        return {
            str(row["id"]): DecisionRecord(
                decision_id=str(row["id"]),
                project=row["project"],
                value=row["value"],
                updated_at=row["updated_at"],
                source_message_id=(
                    str(row["source_message_id"])
                    if row["source_message_id"] is not None
                    else None
                ),
                status=row["status"],
            )
            for row in rows
            if str(row["id"]) in wanted
        }


def _sqlite_ids(values: Sequence[str]) -> list[int]:
    """Convert the current SQLite integer IDs at the adapter boundary."""
    result: list[int] = []
    for value in values:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0 and str(numeric) == str(value):
            result.append(numeric)
    return result
