"""MCP boundary adapter for the production retrieval service."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import Any

from orbit.database.engine import connect
from orbit.retrieval import RetrievalService
from orbit.pageindex.config import build_pageindex_backend, sections_store_path, selector_mode
from orbit.semantic.config import build_semantic_search


def _fts_relax_enabled() -> bool:
    """CELESTIN_FTS_RELAX=0/false/no/off disables bounded FTS5 query relaxation (default on)."""
    return os.environ.get("CELESTIN_FTS_RELAX", "1").strip().lower() not in {"0", "false", "no", "off"}


def _optional_int(name: str) -> int | None:
    """Positive integer from the environment, or None when unset/invalid (the established behavior)."""
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _clamp_excerpt(value: int | None) -> int | None:
    return None if value is None or value < 200 else value


class RetrievalServices:
    """Open a project database per call and delegate all ranking to retrieval."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def search_chat_history(self, project: str, query: str, limit: int) -> dict[str, Any]:
        with closing(connect(self._db_path)) as connection:
            service = RetrievalService(
                connection, semantic=build_semantic_search(self._db_path), fts_relax=_fts_relax_enabled()
            )
            results = service.search_chat_history(project, query, limit)
        response = {
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
        return self._with_retrieval_info(response, service)

    @staticmethod
    def _with_retrieval_info(response: dict[str, Any], service: RetrievalService) -> dict[str, Any]:
        # Only present when semantic search is enabled, so the FTS5-only
        # response schema is unchanged. mode "fts_fallback" means semantic
        # search failed and results are keyword-only (see warnings).
        if service.semantic_enabled or service.documents_enabled:
            response["retrieval"] = service.last_retrieval.as_dict()
        return response

    def retrieve_context(self, project: str, query: str, token_budget: int) -> dict[str, Any]:
        with closing(connect(self._db_path)) as connection:
            service = RetrievalService(
                connection,
                semantic=build_semantic_search(self._db_path),
                documents=build_pageindex_backend(self._db_path),
                fts_relax=_fts_relax_enabled(),
                sections=sections_store_path(self._db_path),
                selector=selector_mode(),
                section_top_k=_optional_int("CELESTIN_SECTION_TOP_K"),
                section_excerpt_bytes=_clamp_excerpt(_optional_int("CELESTIN_SECTION_EXCERPT_BYTES")),
            )
            bundle = service.retrieve_context(project, query, token_budget)

        def public_record(record: Any) -> dict[str, Any]:
            source_message_id = (
                record.record_id
                if record.record_kind == "chat_message"
                else record.source_id
            )
            source = service.last_sources.get(record.record_id)
            if source is not None:
                # Document sections have no source message; `source` names the document and section.
                source_message_id = None
            result = {
                "record_id": record.record_id,
                "source_message_id": source_message_id,
                "created_at": record.timestamp,
                "record_kind": record.record_kind,
                "status": record.status,
            }
            if source is not None:
                result["source"] = source
            if hasattr(record, "content"):
                result["content"] = record.content
            return result

        response = {
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
        return self._with_retrieval_info(response, service)
