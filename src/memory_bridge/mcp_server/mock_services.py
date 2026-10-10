"""Replaceable, in-memory-shaped sample services for the MCP boundary.

These functions return illustrative fixtures only. They do not persist data,
verify project existence, or search a real index. Production adapters can
replace this module without changing the public FastMCP tool definitions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ingest_chat_message(project: str, conversation_id: str, role: str, content: str) -> dict[str, Any]:
    return {
        "project": project,
        "message_id": "mock-message-001",
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "created_at": _timestamp(),
    }


def save_decision(project: str, key: str, value: str, source_message_id: str) -> dict[str, Any]:
    now = _timestamp()
    return {
        "project": project,
        "decision_id": "mock-decision-001",
        "key": key,
        "value": value,
        "status": "draft",
        "source_message_id": source_message_id,
        "created_at": now,
        "updated_at": now,
    }


def search_chat_history(project: str, query: str, limit: int) -> dict[str, Any]:
    results = [{
        "message_id": "mock-message-001",
        "project": project,
        "source_message_id": "mock-message-001",
        "conversation_id": "mock-conversation-001",
        "role": "assistant",
        "content": f"Sample matching message for: {query}",
        "created_at": _timestamp(),
        "score": -1.0,
    }][:limit]
    return {"project": project, "query": query, "results": results}


def retrieve_context(project: str, query: str, token_budget: int) -> dict[str, Any]:
    item = {
        "record_id": "mock-message-001",
        "source_message_id": "mock-message-001",
        "created_at": _timestamp(),
        "record_kind": "chat_message",
        "status": None,
        "content": f"Sample context for: {query}",
        "relevance_score": -1.0,
    }
    rendered = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    token_count = len(rendered.encode("utf-8"))
    items = [item] if token_count <= token_budget else []
    rendered_context = rendered if items else ""
    return {
        "project": project,
        "query": query,
        "items": items,
        "rendered_context": rendered_context,
        "token_count": token_count if items else 0,
        "token_budget": token_budget,
        "token_count_is_estimate": True,
        "token_counter": "utf8-byte-upper-bound",
        "excluded": [] if items else [{
            "record_id": item["record_id"],
            "source_message_id": item["source_message_id"],
            "created_at": item["created_at"],
            "record_kind": item["record_kind"],
            "status": item["status"],
            "reason": "token_budget",
        }],
    }
