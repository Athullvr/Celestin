"""FastMCP public tools for the Memory Bridge."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from memory_bridge.database.engine import DatabaseError
from memory_bridge.repositories._validation import NotFoundError, ValidationError
from memory_bridge.retrieval import SearchIndexUnavailable

from .persistence_services import PersistenceServices, SourceMessageNotFoundError
from .retrieval_services import RetrievalServices

mcp = FastMCP("memory-bridge")

ALLOWED_ROLES = {"system", "developer", "user", "assistant", "tool"}
MIN_SEARCH_LIMIT = 1
MAX_SEARCH_LIMIT = 100
# Operational safety cap for context requests.
MAX_TOKEN_BUDGET = 20_000

# Replaceable adapter instance: tests can inject a temporary database while
# public tool names and arguments remain stable.
persistence_services = PersistenceServices()
retrieval_services = RetrievalServices()


def _error(code: str, message: str) -> ToolError:
    """Create an MCP tool error carrying the contract's stable error payload."""
    return ToolError(json.dumps({"error": {"code": code, "message": message}}))


def _required_string(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("INVALID_ARGUMENT", f"{name} must be a non-empty string.")
    return value


def _validate_project(project: str) -> str:
    return _required_string("project", project)


def _retrieval_call(callback, failure_message: str):
    try:
        return callback()
    except (TypeError, ValueError) as exc:
        raise _error("INVALID_ARGUMENT", "The retrieval request is invalid.") from exc
    except SearchIndexUnavailable as exc:
        raise _error("RETRIEVAL_UNAVAILABLE", "The search index is unavailable.") from exc
    except (DatabaseError, sqlite3.Error) as exc:
        raise _error("RETRIEVAL_UNAVAILABLE", "The retrieval service is unavailable.") from exc
    except Exception as exc:
        raise _error("INTERNAL_ERROR", failure_message) from exc


@mcp.tool(description="Record one chat message in a project.")
def ingest_chat_message(project: str, conversation_id: str, role: str, content: str) -> dict[str, Any]:
    """Record a chat message and return its message ID and UTC creation time."""
    project = _validate_project(project)
    conversation_id = _required_string("conversation_id", conversation_id)
    role = _required_string("role", role)
    if role not in ALLOWED_ROLES:
        raise _error("INVALID_ARGUMENT", "role must be one of: system, developer, user, assistant, tool.")
    content = _required_string("content", content)
    try:
        return persistence_services.ingest_chat_message(project, conversation_id, role, content)
    except ValidationError as exc:
        raise _error("INVALID_ARGUMENT", str(exc)) from exc
    except (DatabaseError, sqlite3.Error) as exc:
        raise _error("STORAGE_ERROR", "The message could not be saved.") from exc
    except Exception as exc:
        raise _error("INTERNAL_ERROR", "The message could not be saved.") from exc


@mcp.tool(description="Save a project decision linked to a source message as a draft.")
def save_decision(project: str, key: str, value: str, source_message_id: str) -> dict[str, Any]:
    """Save a decision draft linked to a message in the same project."""
    project = _validate_project(project)
    key = _required_string("key", key)
    value = _required_string("value", value)
    source_message_id = _required_string("source_message_id", source_message_id)
    try:
        return persistence_services.save_decision(project, key, value, source_message_id)
    except ValidationError as exc:
        raise _error("INVALID_ARGUMENT", str(exc)) from exc
    except (SourceMessageNotFoundError, NotFoundError) as exc:
        raise _error("SOURCE_MESSAGE_NOT_FOUND", "The source message was not found in this project.") from exc
    except (DatabaseError, sqlite3.Error) as exc:
        raise _error("STORAGE_ERROR", "The decision could not be saved.") from exc
    except Exception as exc:
        raise _error("INTERNAL_ERROR", "The decision could not be saved.") from exc


@mcp.tool(description="Search chat messages within one project. Limit must be between 1 and 100.")
def search_chat_history(project: str, query: str, limit: int = 10) -> dict[str, Any]:
    """Search project chat history and return ordered matching messages."""
    project = _validate_project(project)
    query = _required_string("query", query)
    if isinstance(limit, bool) or not isinstance(limit, int) or not MIN_SEARCH_LIMIT <= limit <= MAX_SEARCH_LIMIT:
        raise _error("INVALID_ARGUMENT", "limit must be an integer from 1 through 100.")
    return _retrieval_call(
        lambda: retrieval_services.search_chat_history(project, query, limit),
        "Chat history could not be searched.",
    )


@mcp.tool(description="Build project-scoped context within a positive token budget (maximum 20000). Counts may be estimates.")
def retrieve_context(project: str, query: str, token_budget: int) -> dict[str, Any]:
    """Retrieve traceable project context that fits the requested budget."""
    project = _validate_project(project)
    query = _required_string("query", query)
    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget < 1:
        raise _error("INVALID_ARGUMENT", "token_budget must be a positive integer.")
    if token_budget > MAX_TOKEN_BUDGET:
        raise _error("INVALID_ARGUMENT", f"token_budget must not exceed {MAX_TOKEN_BUDGET}.")
    return _retrieval_call(
        lambda: retrieval_services.retrieve_context(project, query, token_budget),
        "Project context could not be retrieved.",
    )


@mcp.tool(description="Confirm that the Memory Bridge MCP server is responding.")
def ping() -> str:
    """Confirm that the Memory Bridge MCP server is responding."""
    return "MCP Memory Bridge is running."


def main() -> None:
    """Run the server over stdio for local MCP clients."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
