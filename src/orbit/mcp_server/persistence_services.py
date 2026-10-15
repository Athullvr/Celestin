"""Application adapter from MCP operations to a persistence port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orbit.storage.protocol import MemoryStore, SourceMessageNotFoundError
from orbit.storage.sqlite import SQLiteMemoryStore


class PersistenceServices:
    """Map database-neutral stored records to the stable MCP response DTOs.

    ``store`` is injectable for other storage implementations and tests. With
    no explicit store, the established SQLite repositories remain in use.
    ``db_path`` keeps the existing isolated-test and local configuration seam.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        store: MemoryStore | None = None,
    ) -> None:
        self._store = store if store is not None else SQLiteMemoryStore(db_path)

    def ingest_chat_message(
        self, project: str, conversation_id: str, role: str, content: str
    ) -> dict[str, Any]:
        message = self._store.insert_message(project, conversation_id, role, content)
        return {
            "project": message.project,
            "message_id": message.message_id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
        }

    def save_decision(
        self, project: str, key: str, value: str, source_message_id: str
    ) -> dict[str, Any]:
        decision = self._store.save_decision(
            project, key, value, source_message_id, status="draft"
        )
        return {
            "project": decision.project,
            "decision_id": decision.decision_id,
            "key": decision.key,
            "value": decision.value,
            "status": decision.status,
            "source_message_id": decision.source_message_id,
            "created_at": decision.created_at,
            "updated_at": decision.updated_at,
        }
