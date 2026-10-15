"""Operator-invoked PostgreSQL migration command; never used by server startup."""

from __future__ import annotations

import argparse
import os
import sys

from orbit.postgres.migrations.runner import MigrationError, apply_migrations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="celestin-migrate",
        description="Explicitly apply Celestin PostgreSQL schema migrations.",
    )
    parser.add_argument(
        "--dsn-env",
        default="CELESTIN_POSTGRES_DSN",
        help="environment variable containing the PostgreSQL DSN (default: CELESTIN_POSTGRES_DSN)",
    )
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        print(f"Required environment variable {args.dsn_env} is not set.", file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError:
        print(
            "PostgreSQL migrations require the optional dependency; install celestin-memory[postgres].",
            file=sys.stderr,
        )
        return 2

    connection = None
    try:
        connection = psycopg.connect(dsn, autocommit=True)
        result = apply_migrations(connection)
    except MigrationError as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver exceptions can contain connection details; do not echo their text.
        print(
            f"PostgreSQL migration command failed ({type(exc).__name__}); details withheld.",
            file=sys.stderr,
        )
        return 1
    finally:
        if connection is not None:
            connection.close()

    applied = ", ".join(str(version) for version in result.applied_versions) or "none"
    print(f"PostgreSQL migration check complete; current version {result.current_version}; applied: {applied}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
