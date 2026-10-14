"""Explicit PostgreSQL schema migration support.

Importing this package does not load a PostgreSQL driver or connect to a database.
"""

from .authorization import (
    PostgresHostedAuthorizationSession,
    PostgresHostedAuthorizationSessionFactory,
)

__all__ = [
    "PostgresHostedAuthorizationSession",
    "PostgresHostedAuthorizationSessionFactory",
]

