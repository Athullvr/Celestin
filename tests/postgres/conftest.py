"""Opt-in real PostgreSQL fixtures; ordinary tests never contact a database."""

from __future__ import annotations

import os

import pytest

from orbit.postgres.migrations.runner import apply_migrations, load_migrations

from tests.postgres.live_support import (
    LivePostgres,
    UnsafePostgresTestTarget,
    initialize_fresh_database,
    postgres_target_from_environment,
)


def pytest_addoption(parser):
    parser.addoption(
        "--run-postgres-integration",
        action="store_true",
        default=False,
        help="run tests that connect to an explicitly configured disposable PostgreSQL database",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres_integration: requires explicit opt-in and a disposable PostgreSQL database",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-postgres-integration"):
        return
    skip_live = pytest.mark.skip(reason="pass --run-postgres-integration to opt in")
    for item in items:
        if item.get_closest_marker("postgres_integration"):
            item.add_marker(skip_live)


def _assert_fresh_database(connection) -> None:
    """Refuse object classes covered by the migration runner's fresh-db guard.

    The migration runner repeats its own authoritative fresh-database check
    while holding the migration advisory lock. This preflight gives the test
    operator an earlier, test-specific stop condition; it never removes objects.
    """
    ledger = connection.execute(
        "SELECT to_regclass('public.celestin_schema_migrations')"
    ).fetchone()[0]
    if ledger is not None:
        raise UnsafePostgresTestTarget(
            "the designated integration database already has a migration ledger"
        )

    existing_objects = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM pg_catalog.pg_namespace AS n
             WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
               AND n.nspname !~ '^pg_'
            UNION ALL
            SELECT 1
              FROM pg_catalog.pg_class AS c
              JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            UNION ALL
            SELECT 1
              FROM pg_catalog.pg_proc AS p
              JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public'
            UNION ALL
            SELECT 1
              FROM pg_catalog.pg_type AS t
              JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
             WHERE n.nspname = 'public' AND t.typrelid = 0
        )
        """
    ).fetchone()[0]
    if existing_objects:
        raise UnsafePostgresTestTarget(
            "the designated integration database contains unexpected user-created objects"
        )


def _verify_target_identity(connection, target) -> None:
    identity = connection.execute(
        """
        SELECT current_database(), current_user, inet_server_addr()::text,
               inet_server_port(), role.rolsuper
          FROM pg_catalog.pg_roles AS role
         WHERE role.rolname = current_user
        """
    ).fetchone()
    if identity is None:
        raise UnsafePostgresTestTarget("could not verify the PostgreSQL connection identity")
    database, user, host, port, is_superuser = identity
    if (
        database != target.database
        or user != target.user
        or host != target.host
        or port != target.port
        or is_superuser
    ):
        raise UnsafePostgresTestTarget(
            "the connected PostgreSQL identity does not match the configured local test target"
        )


@pytest.fixture(scope="session")
def live_postgres(request):
    """Verify a fresh local target and initialize it through the migration runner.

    This fixture is intentionally destructive only in the narrow sense that it
    creates schema objects in the explicitly named fresh integration database.
    It never drops, truncates, or cleans database objects.
    """
    if not request.config.getoption("--run-postgres-integration"):
        pytest.skip("pass --run-postgres-integration to opt in")

    dsn = os.environ.get("CELESTIN_TEST_POSTGRES_DSN", "")
    if not dsn:
        pytest.skip("CELESTIN_TEST_POSTGRES_DSN is not set")

    try:
        import psycopg
    except ImportError:
        pytest.fail(
            "Psycopg is missing; install the optional extra in the validation environment with "
            '.venv\\validation\\Scripts\\python.exe -m pip install -e ".[postgres,test]"'
        )

    try:
        target = postgres_target_from_environment(
            os.environ
        )
    except UnsafePostgresTestTarget as exc:
        pytest.fail(str(exc))

    connection = None
    failure: str | None = None
    migration_result = None
    migrations = ()
    try:
        connection = psycopg.connect(target.dsn, autocommit=True)
        migrations = load_migrations()
        if not migrations:
            raise RuntimeError("no packaged PostgreSQL migrations were found")
        migration_result = initialize_fresh_database(
            connection,
            target,
            migrations,
            verify_identity=_verify_target_identity,
            assert_fresh=_assert_fresh_database,
            migration_runner=apply_migrations,
        )
    except UnsafePostgresTestTarget as exc:
        failure = str(exc)
    except Exception as exc:
        # Driver exceptions can contain DSNs and other connection details.
        failure = f"PostgreSQL preflight or migration failed ({type(exc).__name__}); details withheld"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                failure = "PostgreSQL preflight connection could not be closed; details withheld"

    if failure:
        pytest.fail(failure)

    return LivePostgres(psycopg, target, migrations, migration_result)


@pytest.fixture
def postgres_connections(live_postgres):
    """Close and verify all test connections and cursors opened by a live test."""
    start = len(live_postgres.connections())
    yield live_postgres
    opened = live_postgres.connections()[start:]
    leaked = [connection for connection in opened if not connection.closed]
    for connection in leaked:
        connection.close()
    open_cursors = [
        cursor
        for connection in opened
        for cursor in connection.cursors
        if not cursor.closed
    ]
    if leaked or open_cursors:
        pytest.fail(
            "live test leaked a PostgreSQL connection or cursor; resources were closed during cleanup"
        )
