"""SQLite persistence layer for the MCP Memory Bridge.

This package owns the schema and all DDL. Repositories in
``memory_bridge.repositories`` build on top of it and are the public
surface for Members 2 and 3.
"""

from memory_bridge.database.engine import (
    DEFAULT_DB_PATH,
    DB_PATH,
    SCHEMA_MIGRATIONS,
    DatabaseError,
    connect,
    initialize,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "DB_PATH",
    "SCHEMA_MIGRATIONS",
    "DatabaseError",
    "connect",
    "initialize",
]
