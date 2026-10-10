"""SQLite engine: schema initialization, connection management, and migrations.

SQLite is the source of truth for raw chat history and canonical project
decisions. This module owns all DDL so the schema is defined in exactly one
place.

Migration strategy: ``PRAGMA user_version`` tracks the applied schema
version. Migrations are ordered scripts in ``SCHEMA_MIGRATIONS``; on
connect, every migration numbered higher than the current ``user_version``
is applied, each inside its own transaction. A clean checkout therefore
initializes itself on first connect with no manual steps.

Environment:
    ``MEMORY_BRIDGE_DB_PATH`` overrides the database location (used by
    tests and anyone running an isolated instance).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/memory_bridge.db")

DB_PATH = Path(
    os.environ.get("MEMORY_BRIDGE_DB_PATH", str(DEFAULT_DB_PATH))
)

# Every key in this dict is a schema version. Applying a migration bumps
# user_version to that key.
SCHEMA_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id              INTEGER PRIMARY KEY,
        project         TEXT NOT NULL,
        conversation_id TEXT NOT NULL DEFAULT 'default',
        role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content         TEXT NOT NULL,
        created_at      TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_chat_messages_project_conversation
        ON chat_messages (project, conversation_id, id);

    CREATE TABLE IF NOT EXISTS project_memory (
        id                INTEGER PRIMARY KEY,
        project           TEXT NOT NULL,
        key               TEXT NOT NULL,
        value             TEXT NOT NULL,
        status            TEXT NOT NULL
            CHECK (status IN ('draft', 'approved', 'deprecated')),
        source_message_id INTEGER REFERENCES chat_messages(id) ON DELETE SET NULL,
        updated_at        TEXT NOT NULL,

        UNIQUE (project, key)
    );

    CREATE INDEX IF NOT EXISTS idx_project_memory_project
        ON project_memory (project);
    """,
}

_ROLE_VALUES = ("user", "assistant", "system")
_STATUS_VALUES = ("draft", "approved", "deprecated")


class DatabaseError(RuntimeError):
    """Raised for database-level failures (SQL errors, broken migration)."""


def _resolve_path(path: str | Path | None) -> Path:
    """Resolve a database path argument, falling back to DB_PATH."""
    if path is not None:
        return Path(path)
    return DB_PATH


def _create_connection(file_path: Path) -> sqlite3.Connection:
    """Open a configured SQLite connection to ``file_path``."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(file_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.Error as exc:  # pragma: no cover - depends on OS state
        raise DatabaseError(f"cannot open database at {file_path}: {exc}") from exc
    return conn


def _migration_applied(conn: sqlite3.Connection, version: int) -> bool:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) >= version


def _apply_migration(conn: sqlite3.Connection, version: int, script: str) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(script)
        # NOTE: sqlite3 executescript() implicitly commits any open
        # transaction, so user_version is raised only after the DDL above
        # has been committed.
        conn.execute(f"PRAGMA user_version = {int(version)}")
    except sqlite3.Error as exc:
        raise DatabaseError(f"schema migration {version} failed: {exc}") from exc


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create if needed) the memory-bridge database.

    Applies any pending schema migrations. Returns an open ``sqlite3``
    connection in autocommit mode (``isolation_level=None``); callers who
    want multi-statement atomicity manage transactions explicitly.
    """
    file_path = _resolve_path(path)
    conn = _create_connection(file_path)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for version in sorted(SCHEMA_MIGRATIONS):
        if _migration_applied(conn, version):
            continue
        _apply_migration(conn, version, SCHEMA_MIGRATIONS[version])


def initialize(path: str | Path | None = None) -> sqlite3.Connection:
    """Backwards-friendly alias for :func:`connect`."""
    return connect(path)


# Value sets shared with the repositories layer for validation.
ROLE_VALUES = _ROLE_VALUES
STATUS_VALUES = _STATUS_VALUES
