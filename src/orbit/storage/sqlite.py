"""SQLite implementation of the database-neutral memory persistence port."""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path

from orbit.database.engine import connect
from orbit.repositories import ChatMessageRepository, DecisionRepository
from orbit.repositories._validation import NotFoundError
from orbit.semantic.config import index_after_write

from .protocol import (
    SourceMessageNotFoundError,
    StoredDecision,
    StoredMessage,
)

logger = logging.getLogger(__name__)


class SQLiteMemoryStore:
    """Delegate memory persistence to the established SQLite repositories."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def insert_message(
        self, project: str, conversation_id: str, role: str, content: str
    ) -> StoredMessage:
        with closing(connect(self._db_path)) as conn:
            repository = ChatMessageRepository(conn)
            message_id = repository.insert(project, conversation_id, role, content)
            # Keep the established project/conversation-scoped readback used to
            # return the database timestamp with the generated ID.
            row = next(
                (
                    item
                    for item in repository.list_for_conversation(project, conversation_id)
                    if item["id"] == message_id
                ),
                None,
            )
            if row is None:
                raise RuntimeError("inserted message could not be read back")

            # The authoritative row is committed before indexing. Keep derived
            # semantic indexing best-effort so it cannot fail message ingestion.
            try:
                index_after_write(conn, "chat_message", message_id, self._db_path)
            except Exception as exc:  # defensive if an index implementation fails to contain errors
                logger.warning(
                    "semantic indexing deferred for a chat message (%s)", type(exc).__name__
                )

            return StoredMessage(
                message_id=str(row["id"]),
                project=project,
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )

    def save_decision(
        self,
        project: str,
        key: str,
        value: str,
        source_message_id: str,
        status: str = "draft",
    ) -> StoredDecision:
        database_message_id = _sqlite_message_id(source_message_id)
        with closing(connect(self._db_path)) as conn:
            try:
                row = DecisionRepository(conn).save(
                    project=project,
                    key=key,
                    value=value,
                    source_message_id=database_message_id,
                    status=status,
                )
            except NotFoundError as exc:
                raise SourceMessageNotFoundError from exc
            return _stored_decision(row)

    def update_decision_status(
        self, project: str, key: str, status: str
    ) -> StoredDecision:
        with closing(connect(self._db_path)) as conn:
            return _stored_decision(
                DecisionRepository(conn).update_status(project, key, status)
            )


def _sqlite_message_id(source_message_id: str) -> int:
    """Translate the current SQLite ID representation at the adapter edge."""
    try:
        message_id = int(source_message_id)
    except (TypeError, ValueError) as exc:
        raise SourceMessageNotFoundError from exc
    if message_id < 1 or str(message_id) != source_message_id:
        raise SourceMessageNotFoundError
    return message_id


def _stored_decision(row: dict) -> StoredDecision:
    # The current SQLite schema stores updated_at only. Preserve the existing
    # MCP behavior of using that value for both timestamps.
    updated_at = row["updated_at"]
    source_id = row["source_message_id"]
    return StoredDecision(
        decision_id=str(row["id"]),
        project=row["project"],
        key=row["key"],
        value=row["value"],
        status=row["status"],
        source_message_id=str(source_id) if source_id is not None else None,
        created_at=updated_at,
        updated_at=updated_at,
    )
