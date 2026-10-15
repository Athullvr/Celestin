"""Safety checks and connection tracking for opt-in PostgreSQL tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import ipaddress
import re
from typing import Callable, Mapping


class UnsafePostgresTestTarget(ValueError):
    """The configured target does not satisfy the live-test safety policy."""


_DATABASE_NAME = re.compile(r"^celestin_it_[0-9]{8}_[a-f0-9]{8}$")
_ROLE_NAME = re.compile(r"^celestin_it_user_[a-f0-9]{8}$")
# One explicitly approved target for the current live-test run. It remains
# subject to the same DSN, runtime identity, non-superuser, and empty-schema
# checks as nonce-named targets. After migration it is no longer reusable.
_APPROVED_TARGET = (
    "celestin_it_20261014_a7f3c9",
    "celestin_it_20261014_a7f3c9",
    "127.0.0.1",
    5432,
)
_REQUIRED_ENV = (
    "CELESTIN_TEST_POSTGRES_DSN",
    "CELESTIN_TEST_POSTGRES_DATABASE",
    "CELESTIN_TEST_POSTGRES_USER",
    "CELESTIN_TEST_POSTGRES_HOST",
    "CELESTIN_TEST_POSTGRES_PORT",
)


@dataclass(frozen=True, repr=False)
class PostgresTestTarget:
    """Verified connection coordinates; the secret DSN is omitted from repr."""

    dsn: str = field(repr=False)
    database: str
    user: str
    host: str
    port: int

    def __repr__(self) -> str:
        return (
            "PostgresTestTarget(database={!r}, user={!r}, host={!r}, port={!r})"
        ).format(self.database, self.user, self.host, self.port)


def postgres_target_from_environment(
    environ: Mapping[str, str],
    parse_conninfo: Callable[[str], Mapping[str, str]],
) -> PostgresTestTarget:
    """Require an exact, local, nonce-named disposable database configuration."""

    values: dict[str, str] = {}
    for name in _REQUIRED_ENV:
        value = environ.get(name, "").strip()
        if not value:
            raise UnsafePostgresTestTarget(f"{name} must be set")
        values[name] = value

    database = values["CELESTIN_TEST_POSTGRES_DATABASE"]
    approved_database = database == _APPROVED_TARGET[0]
    if database == "celestin_schema_test_v2" or (
        not approved_database and not _DATABASE_NAME.fullmatch(database)
    ):
        raise UnsafePostgresTestTarget(
            "the test database must use celestin_it_YYYYMMDD_<8-hex-nonce> "
            "or the exact approved target"
        )

    user = values["CELESTIN_TEST_POSTGRES_USER"]
    if approved_database:
        if user != _APPROVED_TARGET[1]:
            raise UnsafePostgresTestTarget(
                "the approved database requires its exact approved role"
            )
    elif not _ROLE_NAME.fullmatch(user):
        raise UnsafePostgresTestTarget(
            "the test role must use celestin_it_user_<8-hex-nonce>"
        )
    if not approved_database and user.rsplit("_", 1)[-1] != database.rsplit("_", 1)[-1]:
        raise UnsafePostgresTestTarget(
            "the database and test role must use the same eight-hex nonce"
        )

    host = values["CELESTIN_TEST_POSTGRES_HOST"]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise UnsafePostgresTestTarget("the test host must be a loopback IP address") from None
    if not address.is_loopback:
        raise UnsafePostgresTestTarget("the test host must be a loopback IP address")

    try:
        port = int(values["CELESTIN_TEST_POSTGRES_PORT"])
    except ValueError:
        raise UnsafePostgresTestTarget("the test port must be an integer") from None
    if not 1 <= port <= 65535:
        raise UnsafePostgresTestTarget("the test port is out of range")
    if approved_database and (host, port) != (_APPROVED_TARGET[2], _APPROVED_TARGET[3]):
        raise UnsafePostgresTestTarget(
            "the approved database requires its exact loopback host and port"
        )

    try:
        options = parse_conninfo(values["CELESTIN_TEST_POSTGRES_DSN"])
    except Exception:
        # Conninfo parser exceptions can include the input DSN and its password.
        raise UnsafePostgresTestTarget("the test DSN is invalid") from None

    expected = {"dbname": database, "user": user, "host": host, "port": str(port)}
    if any(options.get(key) != value for key, value in expected.items()):
        raise UnsafePostgresTestTarget(
            "the DSN must explicitly match the configured database, role, host, and port"
        )

    return PostgresTestTarget(
        dsn=values["CELESTIN_TEST_POSTGRES_DSN"],
        database=database,
        user=user,
        host=str(address),
        port=port,
    )


class TrackedConnection:
    """Track cursors and connection closure for real-driver cleanup checks."""

    def __init__(self, connection) -> None:
        self.raw = connection
        self.cursors = []

    def execute(self, query, params=(), **kwargs):
        cursor = self.raw.execute(query, params, **kwargs)
        self.cursors.append(cursor)
        return cursor

    def transaction(self):
        return self.raw.transaction()

    def close(self) -> None:
        self.raw.close()

    @property
    def closed(self) -> bool:
        return bool(self.raw.closed)


class LivePostgres:
    """A verified target and tracked per-test connections."""

    def __init__(self, psycopg, target: PostgresTestTarget, migrations, migration_result):
        self.psycopg = psycopg
        self.target = target
        self.migrations = migrations
        self.migration_result = migration_result
        self._connections: list[TrackedConnection] = []

    def connect(self, **kwargs) -> TrackedConnection:
        connection = TrackedConnection(self.psycopg.connect(self.target.dsn, **kwargs))
        self._connections.append(connection)
        return connection

    @contextmanager
    def connection(self, **kwargs):
        """Open and reliably close one tracked connection."""
        connection = self.connect(**kwargs)
        try:
            yield connection
        finally:
            connection.close()

    def connections(self) -> tuple[TrackedConnection, ...]:
        return tuple(self._connections)

    def close_connections(self) -> None:
        for connection in self._connections:
            if not connection.closed:
                connection.close()


def initialize_fresh_database(
    connection,
    target: PostgresTestTarget,
    migrations,
    *,
    verify_identity: Callable,
    assert_fresh: Callable,
    migration_runner: Callable,
):
    """Verify, migrate once through the runner, and verify the resulting ledger."""

    verify_identity(connection, target)
    assert_fresh(connection)
    result = migration_runner(connection, migrations)
    ledger_rows = connection.execute(
        "SELECT version, name, checksum FROM public.celestin_schema_migrations ORDER BY version"
    ).fetchall()
    expected_rows = [
        (migration.version, migration.name, migration.checksum)
        for migration in migrations
    ]
    if (
        result.applied_versions != tuple(migration.version for migration in migrations)
        or result.current_version != migrations[-1].version
        or ledger_rows != expected_rows
    ):
        raise UnsafePostgresTestTarget(
            "migration result or ledger does not match the packaged migrations"
        )
    return result
