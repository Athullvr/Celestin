"""Shared validation helpers for repositories."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from orbit.database.engine import ROLE_VALUES, STATUS_VALUES


class ValidationError(ValueError):
    """Raised when repository input fails validation."""


class NotFoundError(KeyError):
    """Raised when a record ID does not exist."""


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with ``Z`` designator."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_project(project: str) -> str:
    if not isinstance(project, str) or not project.strip():
        raise ValidationError("project must be a non-empty string")
    return project.strip()


def validate_conversation_id(conversation_id: str) -> str:
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValidationError("conversation_id must be a non-empty string")
    return conversation_id.strip()


def validate_role(role: str) -> str:
    if not isinstance(role, str) or role not in ROLE_VALUES:
        allowed = ", ".join(ROLE_VALUES)
        raise ValidationError(
            f"invalid role {role!r}: must be one of {allowed}"
        )
    return role


def validate_status(status: str) -> str:
    if not isinstance(status, str) or status not in STATUS_VALUES:
        allowed = ", ".join(STATUS_VALUES)
        raise ValidationError(
            f"invalid status {status!r}: must be one of {allowed}"
        )
    return status


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not key.strip():
        raise ValidationError("key must be a non-empty string")
    return key.strip()


def validate_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("value must be a string")
    return value


def validate_source_message_id(
    conn: sqlite3.Connection, project: str, source_message_id: int | None
) -> int | None:
    """Validate an optional chat-message reference within its project.

    Returns the validated ID. Raises ``NotFoundError`` when the ID is not
    an existing ``chat_messages.id`` so broken references never enter the
    canonical memory table.
    """
    if source_message_id is None:
        return None
    if not isinstance(source_message_id, int) or isinstance(source_message_id, bool):
        raise ValidationError("source_message_id must be an integer or None")
    row = conn.execute(
        "SELECT 1 FROM chat_messages WHERE id = ? AND project = ?",
        (source_message_id, project),
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"source_message_id {source_message_id} does not reference an "
            "existing chat message in this project"
        )
    return source_message_id
