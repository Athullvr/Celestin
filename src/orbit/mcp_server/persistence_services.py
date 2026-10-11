"""Adapter from MCP operations to Member 1's SQLite repositories."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from orbit.database.engine import connect
from orbit.repositories import ChatMessageRepository, DecisionRepository
from orbit.repositories._validation import NotFoundError
from orbit.semantic.config import index_after_write


class SourceMessageNotFoundError(LookupError):
    """The source message does not exist in the requested project."""


class PersistenceServices:
    """Repository-backed persistence adapter.

    ``db_path`` is injectable for isolated tests. The default uses Member 1's
    ``MEMORY_BRIDGE_DB_PATH`` configuration and persistent SQLite database.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def ingest_chat_message(
        self, project: str, conversation_id: str, role: str, content: str
    ) -> dict[str, Any]:
        with closing(connect(self._db_path)) as conn:
            repository = ChatMessageRepository(conn)
            message_id = repository.insert(project, conversation_id, role, content)
            # The public repository API returns the generated ID from insert;
            # read it back through the project- and conversation-scoped API to
            # preserve the database timestamp in the MCP response.
            row = next(
                (item for item in repository.list_for_conversation(project, conversation_id)
                 if item["id"] == message_id),
                None,
            )
            if row is None:
                raise RuntimeError("inserted message could not be read back")
            # SQLite is committed; semantic indexing is best-effort and
            # repaired by `celestin-index sync` if it fails.
            index_after_write(conn, "chat_message", message_id, self._db_path)
            return {
                "project": project,
                "message_id": str(row["id"]),
                "conversation_id": row["conversation_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
    def save_decision(
        self, project: str, key: str, value: str, source_message_id: str
    ) -> dict[str, Any]:
        try:
            database_message_id = int(source_message_id)
        except (TypeError, ValueError) as exc:
            raise SourceMessageNotFoundError from exc
        if database_message_id < 1 or str(database_message_id) != source_message_id:
            raise SourceMessageNotFoundError

        with closing(connect(self._db_path)) as conn:
            decision = DecisionRepository(conn).save(
                project=project,
                key=key,
                value=value,
                source_message_id=database_message_id,
                status="draft",
            )
            updated_at = decision["updated_at"]
            return {
                "project": project,
                "decision_id": str(decision["id"]),
                "key": decision["key"],
                "value": decision["value"],
                "status": decision["status"],
                "source_message_id": str(decision["source_message_id"]),
                # Member 1's current schema stores updated_at only. For a new
                # decision both timestamps are identical; an upsert cannot
                # recover the original created_at without a schema change.
                "created_at": updated_at,
                "updated_at": updated_at,
            }
