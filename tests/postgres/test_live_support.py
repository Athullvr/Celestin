"""Pure safety-policy tests for the opt-in PostgreSQL target parser."""

from __future__ import annotations

import pytest

from tests.postgres.live_support import (
    UnsafePostgresTestTarget,
    initialize_fresh_database,
    postgres_target_from_environment,
)


NONCE = "a1b2c3d4"


def target_environment(**changes):
    values = {
        "CELESTIN_TEST_POSTGRES_DSN": (
            f"host=127.0.0.1 port=5432 dbname=celestin_it_20261014_{NONCE} "
            f"user=celestin_it_user_{NONCE}"
        ),
        "CELESTIN_TEST_POSTGRES_DATABASE": f"celestin_it_20261014_{NONCE}",
        "CELESTIN_TEST_POSTGRES_USER": f"celestin_it_user_{NONCE}",
        "CELESTIN_TEST_POSTGRES_HOST": "127.0.0.1",
        "CELESTIN_TEST_POSTGRES_PORT": "5432",
    }
    values.update(changes)
    return values


def test_accepts_only_explicit_matching_loopback_target_and_hides_dsn():
    target = postgres_target_from_environment(target_environment())

    assert target.database == f"celestin_it_20261014_{NONCE}"
    assert target.user == f"celestin_it_user_{NONCE}"
    assert target.host == "127.0.0.1"
    assert target.port == 5432
    assert target.dsn not in repr(target)
    assert "password" not in repr(target).lower()


def test_accepts_exactly_the_approved_non_nonce_target():
    approved_database = "celestin_it_20261014_a7f3c9"
    values = target_environment(
        CELESTIN_TEST_POSTGRES_DSN=(
            f"host=127.0.0.1 port=5432 dbname={approved_database} user={approved_database}"
        ),
        CELESTIN_TEST_POSTGRES_DATABASE=approved_database,
        CELESTIN_TEST_POSTGRES_USER=approved_database,
    )

    target = postgres_target_from_environment(values)

    assert target.database == approved_database
    assert target.user == approved_database
    assert target.host == "127.0.0.1"
    assert target.port == 5432
    assert target.dsn not in repr(target)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"CELESTIN_TEST_POSTGRES_DATABASE": "celestin_schema_test_v2"}, "test database"),
        ({"CELESTIN_TEST_POSTGRES_DATABASE": "celestin_prod"}, "test database"),
        ({"CELESTIN_TEST_POSTGRES_DATABASE": "celestin_it_20261014_b7f3c9"}, "test database"),
        ({"CELESTIN_TEST_POSTGRES_USER": "postgres"}, "test role"),
        ({"CELESTIN_TEST_POSTGRES_USER": "celestin_it_user_ffffffff"}, "same eight-hex nonce"),
        ({"CELESTIN_TEST_POSTGRES_HOST": "192.0.2.50"}, "loopback"),
        ({"CELESTIN_TEST_POSTGRES_PORT": "5433"}, "configured target"),
        (
            {
                "CELESTIN_TEST_POSTGRES_DSN": (
                    "host=127.0.0.1 port=5432 dbname=other "
                    "user=celestin_it_user_a1b2c3d4"
                )
            },
            "configured target",
        ),
    ],
)
def test_rejects_unsafe_or_mismatched_target(changes, message):
    with pytest.raises(UnsafePostgresTestTarget, match=message):
        postgres_target_from_environment(target_environment(**changes))


def test_missing_target_field_is_rejected_without_database_fallback():
    values = target_environment()
    del values["CELESTIN_TEST_POSTGRES_DSN"]

    with pytest.raises(UnsafePostgresTestTarget, match="CELESTIN_TEST_POSTGRES_DSN must be set"):
        postgres_target_from_environment(values)


@pytest.mark.parametrize(
    "dsn, message",
    [
        (
            "host=127.0.0.1 port=5432 dbname=celestin_it_20261014_a1b2c3d4 "
            "user=celestin_it_user_a1b2c3d4 password=do-not-echo",
            "password parameters",
        ),
        (
            "host=127.0.0.1 port=5432 dbname=celestin_it_20261014_a1b2c3d4 "
            "user=celestin_it_user_a1b2c3d4 sslpassword=do-not-echo",
            "password parameters",
        ),
        (
            "host=127.0.0.1 port=5432 dbname=celestin_it_20261014_a1b2c3d4 "
            "user=celestin_it_user_a1b2c3d4 application_name=unexpected",
            "exactly host, port, dbname, and user",
        ),
        (
            "host=127.0.0.1 host=127.0.0.1 port=5432 "
            "dbname=celestin_it_20261014_a1b2c3d4 user=celestin_it_user_a1b2c3d4",
            "duplicate parameter",
        ),
        (
            "host=127.0.0.1 host=127.0.0.2 port=5432 "
            "dbname=celestin_it_20261014_a1b2c3d4 user=celestin_it_user_a1b2c3d4",
            "duplicate parameter",
        ),
        ("postgresql://user:do-not-echo@127.0.0.1:5432/db", "malformed"),
        ("host='127.0.0.1' port=5432", "malformed"),
        ("host= port=5432", "malformed"),
        (
            "host=127.0.0.1 port=bad dbname=celestin_it_20261014_a1b2c3d4 "
            "user=celestin_it_user_a1b2c3d4",
            "configured target",
        ),
    ],
)
def test_rejects_password_unknown_duplicate_and_malformed_dsns_without_echoing_secrets(
    dsn, message
):
    values = target_environment(CELESTIN_TEST_POSTGRES_DSN=dsn)
    with pytest.raises(UnsafePostgresTestTarget, match=message) as error:
        postgres_target_from_environment(values)
    assert "do-not-echo" not in str(error.value)


def test_approved_target_rejects_a_different_role_or_endpoint():
    approved_database = "celestin_it_20261014_a7f3c9"
    base = {
        "CELESTIN_TEST_POSTGRES_DATABASE": approved_database,
        "CELESTIN_TEST_POSTGRES_USER": approved_database,
        "CELESTIN_TEST_POSTGRES_HOST": "127.0.0.1",
        "CELESTIN_TEST_POSTGRES_PORT": "5432",
    }
    for changes, expected in (
        ({"CELESTIN_TEST_POSTGRES_USER": "celestin_it_user_a7f3c9"}, "exact approved role"),
        ({"CELESTIN_TEST_POSTGRES_HOST": "127.0.0.2"}, "exact loopback host and port"),
        ({"CELESTIN_TEST_POSTGRES_PORT": "5433"}, "exact loopback host and port"),
    ):
        values = target_environment(**(base | changes))
        # Keep the DSN synchronized so the failure proves the allowlist itself
        # rejects the changed identity, rather than only catching DSN mismatch.
        values["CELESTIN_TEST_POSTGRES_DSN"] = (
            f"host={values['CELESTIN_TEST_POSTGRES_HOST']} "
            f"port={values['CELESTIN_TEST_POSTGRES_PORT']} "
            f"dbname={values['CELESTIN_TEST_POSTGRES_DATABASE']} "
            f"user={values['CELESTIN_TEST_POSTGRES_USER']}"
        )
        with pytest.raises(UnsafePostgresTestTarget, match=expected):
            postgres_target_from_environment(values)


class _MigrationResult:
    def __init__(self, applied_versions, current_version):
        self.applied_versions = tuple(applied_versions)
        self.current_version = current_version


class _LedgerConnection:
    def __init__(self, ledger_rows):
        self.ledger_rows = ledger_rows
        self.queries = []

    def execute(self, query):
        self.queries.append(query)
        return self

    def fetchall(self):
        return self.ledger_rows


def test_fresh_target_checks_identity_and_emptiness_before_one_migration_run():
    from types import SimpleNamespace

    migrations = (
        SimpleNamespace(version=1, name="0001_base.sql", checksum="abc"),
        SimpleNamespace(version=2, name="0002_status.sql", checksum="def"),
    )
    connection = _LedgerConnection([(1, "0001_base.sql", "abc"), (2, "0002_status.sql", "def")])
    events = []

    def runner(_connection, loaded):
        events.append(("migration", loaded))
        return _MigrationResult((1, 2), 2)

    result = initialize_fresh_database(
        connection,
        object(),
        migrations,
        verify_identity=lambda *_: events.append(("identity",)),
        assert_fresh=lambda *_: events.append(("fresh",)),
        migration_runner=runner,
    )

    assert [event[0] for event in events] == ["identity", "fresh", "migration"]
    assert result.applied_versions == (1, 2)
    assert len([event for event in events if event[0] == "migration"]) == 1
    assert len(connection.queries) == 1


def test_fresh_target_never_migrates_after_failed_identity_or_empty_check():
    migration_calls = []
    migrations = (type("M", (), {"version": 1, "name": "0001.sql", "checksum": "abc"})(),)
    for failed_check in ("identity", "fresh"):
        def fail(*_args):
            raise UnsafePostgresTestTarget(f"{failed_check} failed")

        kwargs = {
            "verify_identity": fail if failed_check == "identity" else lambda *_: None,
            "assert_fresh": fail if failed_check == "fresh" else lambda *_: None,
            "migration_runner": lambda *_: migration_calls.append("run"),
        }
        with pytest.raises(UnsafePostgresTestTarget):
            initialize_fresh_database(_LedgerConnection([]), object(), migrations, **kwargs)
    assert migration_calls == []
