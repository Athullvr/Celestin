"""Explicit, serialized PostgreSQL schema migrations.

This module uses the small ``execute``/``transaction`` surface provided by
psycopg 3, but deliberately does not import the optional driver. Applications
must invoke the separate migration command; SQLite startup never calls here.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
import re
from typing import Protocol, Sequence


LEDGER_TABLE = "public.celestin_schema_migrations"
# A stable, project-specific 64-bit PostgreSQL advisory-lock key (ASCII CELESTIN).
MIGRATION_LOCK_KEY = 0x43454C455354494E
_MIGRATION_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when the migration history is unsafe or a migration fails."""


class MigrationConnection(Protocol):
    """The connection operations used by the runner (implemented by psycopg)."""

    autocommit: bool

    def execute(self, query: str, params: object = ..., *, prepare: bool | None = ...) -> object: ...

    def transaction(self) -> object: ...


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        """SHA-256 of the exact UTF-8 SQL text shipped with this release."""
        return sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationResult:
    applied_versions: tuple[int, ...]
    current_version: int


def load_migrations() -> tuple[Migration, ...]:
    """Load ordered SQL resources packaged with Celestin."""
    directory = resources.files("orbit.postgres.migrations")
    migrations: list[Migration] = []
    for item in directory.iterdir():
        match = _MIGRATION_NAME.fullmatch(item.name)
        if match is None:
            continue
        migrations.append(
            Migration(
                version=int(match.group(1)),
                name=item.name,
                sql=item.read_text(encoding="utf-8"),
            )
        )
    return validate_migrations(migrations)


def validate_migrations(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    """Require unique, contiguous versions beginning at 1."""
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    expected = tuple(range(1, len(ordered) + 1))
    actual = tuple(migration.version for migration in ordered)
    if actual != expected:
        raise MigrationError(
            f"migration versions must be unique and contiguous from 1; found {actual}"
        )
    if any(not migration.name or not migration.sql.strip() for migration in ordered):
        raise MigrationError("every migration must have a name and non-empty SQL")
    if len({migration.name for migration in ordered}) != len(ordered):
        raise MigrationError("migration names must be unique")
    return ordered


_LEDGER_EXISTS_SQL = "SELECT to_regclass(%s)"
_HAS_EXISTING_OBJECTS_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_namespace n
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
      AND n.nspname !~ '^pg_'
    UNION ALL
    SELECT 1
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND c.relname <> 'celestin_schema_migrations'
    UNION ALL
    SELECT 1
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
    UNION ALL
    SELECT 1
    FROM pg_catalog.pg_type t
    JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typrelid = 0
)
"""
_CREATE_LEDGER_SQL = f"""
CREATE TABLE {LEDGER_TABLE} (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{{64}}$'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
_READ_LEDGER_SQL = f"SELECT version, name, checksum FROM {LEDGER_TABLE} ORDER BY version"
_INSERT_LEDGER_SQL = f"""
INSERT INTO {LEDGER_TABLE} (version, name, checksum)
VALUES (%s, %s, %s)
"""


def apply_migrations(
    connection: MigrationConnection,
    migrations: Sequence[Migration] | None = None,
) -> MigrationResult:
    """Apply pending migrations under one session-level advisory lock.

    Each migration and its ledger row commit atomically. An empty database is
    required when no ledger exists; legacy/untracked schemas are never adopted
    automatically. The caller owns opening/closing the connection.
    """
    ordered = validate_migrations(migrations if migrations is not None else load_migrations())
    if getattr(connection, "autocommit", None) is not True:
        raise MigrationError(
            "migration connection must use autocommit=True; each migration is committed explicitly"
        )
    _lock(connection)
    try:
        ledger_exists = connection.execute(_LEDGER_EXISTS_SQL, (LEDGER_TABLE,)).fetchone()[0]
        if ledger_exists is None:
            has_objects = bool(connection.execute(_HAS_EXISTING_OBJECTS_SQL).fetchone()[0])
            if has_objects:
                raise MigrationError(
                    "database has user objects but no Celestin migration ledger; "
                    "refusing to adopt or modify this database"
                )
            try:
                with connection.transaction():
                    connection.execute("SET LOCAL search_path TO public")
                    connection.execute(_CREATE_LEDGER_SQL)
            except Exception as exc:
                raise MigrationError("could not create the Celestin migration ledger") from exc

        try:
            applied_rows = connection.execute(_READ_LEDGER_SQL).fetchall()
        except Exception as exc:
            raise MigrationError("existing Celestin migration ledger is unreadable or incompatible") from exc
        applied: dict[int, tuple[str, str]] = {}
        for version, name, checksum in applied_rows:
            version = int(version)
            if version in applied:
                raise MigrationError(f"migration ledger contains duplicate version {version}")
            applied[version] = (str(name), str(checksum))

        if not applied:
            has_untracked_objects = bool(
                connection.execute(_HAS_EXISTING_OBJECTS_SQL).fetchone()[0]
            )
            if has_untracked_objects:
                raise MigrationError(
                    "database has schema objects but no applied migration records; "
                    "refusing to adopt or modify this database"
                )

        available = {migration.version: migration for migration in ordered}
        for version, (name, checksum) in applied.items():
            migration = available.get(version)
            if migration is None:
                raise MigrationError(
                    f"database has migration version {version} ({name}) not present in this release"
                )
            if name != migration.name or checksum != migration.checksum:
                raise MigrationError(
                    f"migration {version} checksum or name differs from the applied migration; "
                    "restore the original migration file and add a new migration instead"
                )

        expected_applied = set(range(1, max(applied, default=0) + 1))
        if set(applied) != expected_applied:
            raise MigrationError("migration ledger has a version gap; refusing to continue")

        newly_applied: list[int] = []
        for migration in ordered:
            if migration.version in applied:
                continue
            try:
                with connection.transaction():
                    connection.execute("SET LOCAL search_path TO public")
                    # Migration files contain multiple DDL statements. Psycopg
                    # must use the simple-query protocol for this one call.
                    connection.execute(migration.sql, prepare=False)
                    connection.execute(
                        _INSERT_LEDGER_SQL,
                        (migration.version, migration.name, migration.checksum),
                    )
            except Exception as exc:
                raise MigrationError(
                    f"migration {migration.version} ({migration.name}) failed; "
                    "its transaction was rolled back"
                ) from exc
            newly_applied.append(migration.version)
        return MigrationResult(
            applied_versions=tuple(newly_applied),
            current_version=max(available, default=0),
        )
    finally:
        _unlock(connection)


def _lock(connection: MigrationConnection) -> None:
    try:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
    except Exception as exc:
        raise MigrationError("could not acquire the PostgreSQL migration lock") from exc


def _unlock(connection: MigrationConnection) -> None:
    try:
        result = connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
        unlocked = result.fetchone()[0]
        if not unlocked:
            raise MigrationError("PostgreSQL migration lock was not held at release")
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("could not release the PostgreSQL migration lock") from exc
