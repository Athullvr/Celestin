"""SQLite persistence layer for Orbit.

This package owns the schema and all DDL. Repositories in
``orbit.repositories`` build on top of it and are the public
surface for Members 2 and 3.
"""

from orbit.database.engine import (
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
