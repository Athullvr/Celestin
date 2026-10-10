"""Engine tests: initialization, idempotency, persistence across restarts."""

from __future__ import annotations

import sqlite3

import pytest

from memory_bridge.database.engine import (
    SCHEMA_MIGRATIONS,
    connect,
)


def test_connect_creates_tables_from_clean_checkout(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"chat_messages", "project_memory"} <= names


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "fresh.db"
    first = connect(path)
    first.close()
    second = connect(path)  # must not raise or duplicate anything
    row = second.execute("PRAGMA user_version").fetchone()
    assert int(row[0]) == max(SCHEMA_MIGRATIONS)


def test_schema_check_constraints_present(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='project_memory'"
    ).fetchone()[0]
    assert "'draft', 'approved', 'deprecated'" in sql
    assert "UNIQUE (project, key)" in sql
    assert "REFERENCES chat_messages(id)" in sql


def test_persists_across_restart(tmp_path):
    first = connect(tmp_path / "test.db")
    first.execute(
        "INSERT INTO chat_messages (project, conversation_id, role, content, created_at)"
        " VALUES ('proj-a', 'conv-1', 'user', 'remember me', '2026-01-01T00:00:00Z')"
    )
    first.commit()
    first.close()

    # Simulate a restart: brand-new connection to the same file.
    second = connect(tmp_path / "test.db")
    rows = second.execute(
        "SELECT content FROM chat_messages ORDER BY id"
    ).fetchall()
    assert [r[0] for r in rows] == ["remember me"]


def test_check_constraint_rejects_bad_status(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO project_memory"
            " (project, key, value, status, source_message_id, updated_at)"
            " VALUES ('p', 'k', 'v', 'deleted', NULL, '2026-01-01T00:00:00Z')"
        )
