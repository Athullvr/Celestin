"""MCP boundary adapter for the production retrieval service."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from memory_bridge.database.engine import connect
from memory_bridge.retrieval import RetrievalService


class RetrievalServices:
    """Open a project database per call and delegate all ranking to retrieval."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def search_chat_history(self, project: str, query: str, limit: int) -> dict[str, Any]:
        with closing(connect(self._db_path)) as connection:
            results = RetrievalService(connection).search_chat_history(project, query, limit)
        return {
            "project": project,
            "query": query,
            "results": [
                {
                    "message_id": result.message_id,
                    "project": result.project_id,
                    "source_message_id": result.message_id,
                    "conversation_id": result.source_id,
                    "role": None,
                    "content": result.content,
                    "created_at": result.timestamp,
                    "score": result.relevance_score,
                }
                for result in results
            ],
        }

    def retrieve_context(self, project: str, query: str, token_budget: int) -> dict[str, Any]:
        with closing(connect(self._db_path)) as connection:
            bundle = RetrievalService(connection).retrieve_context(project, query, token_budget)

        def public_record(record: Any) -> dict[str, Any]:
            source_message_id = (
                record.record_id
                if record.record_kind == "chat_message"
                else record.source_id
            )
            result = {
                "record_id": record.record_id,
                "source_message_id": source_message_id,
                "created_at": record.timestamp,
                "record_kind": record.record_kind,
                "status": record.status,
            }
            if hasattr(record, "content"):
                result["content"] = record.content
            return result

        return {
            "project": project,
            "query": query,
            "items": [
                {**public_record(item), "relevance_score": item.relevance_score}
                for item in bundle.items
            ],
            "rendered_context": bundle.rendered_context,
            "token_count": bundle.token_count,
            "token_budget": bundle.token_budget,
            "token_count_is_estimate": bundle.token_count_is_estimate,
            "token_counter": bundle.token_counter,
            "excluded": [
                {**public_record(item), "reason": item.reason}
                for item in bundle.excluded
                if item.reason in {"token_budget", "duplicate_content"}
            ],
        }
