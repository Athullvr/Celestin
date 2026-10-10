"""Decision repository tests."""

from __future__ import annotations

import pytest

from memory_bridge.repositories._validation import NotFoundError, ValidationError
from memory_bridge.repositories.decisions import (
    DecisionRepository,
    save_decision,
)


def test_save_returns_full_row(decisions, db_conn):
    d = decisions.save("proj-a", "uses-sqlite", "SQLite is the source of truth")
    assert d["project"] == "proj-a"
    assert d["key"] == "uses-sqlite"
    assert d["status"] == "draft"
    assert d["source_message_id"] is None
    assert d["updated_at"]


def test_contract_function_save_and_defaults(db_conn):
    d = save_decision("proj-a", "k", "v", conn=db_conn)
    assert d["status"] == "draft"


def test_upsert_overwrites_same_project_key(decisions):
    first = decisions.save("proj-a", "k", "v1")
    second = decisions.save("proj-a", "k", "v2")
    assert second["id"] == first["id"]  # same row updated, not duplicated
    assert second["value"] == "v2"
    assert second["updated_at"] >= first["updated_at"]


def test_same_key_different_projects_are_separate(decisions):
    decisions.save("proj-a", "k", "value-a")
    decisions.save("proj-b", "k", "value-b")
    assert decisions.get("proj-a", "k")["value"] == "value-a"
    assert decisions.get("proj-b", "k")["value"] == "value-b"


def test_status_transitions(decisions):
    decisions.save("proj-a", "k", "v", status="draft")
    assert decisions.get("proj-a", "k")["status"] == "draft"
    approved = decisions.update_status("proj-a", "k", "approved")
    assert approved["status"] == "approved"
    deprecated = decisions.update_status("proj-a", "k", "deprecated")
    assert deprecated["status"] == "deprecated"


def test_invalid_status_rejected(decisions):
    with pytest.raises(ValidationError):
        decisions.save("proj-a", "k", "v", status="published")
    with pytest.raises(ValidationError):
        decisions.update_status("proj-a", "k", "ARCHIVED")
    # Nonexistent row still validates the status before lookup
    with pytest.raises(NotFoundError):
        decisions.update_status("proj-a", "missing", "approved")


def test_invalid_source_message_id_rejected(decisions):
    with pytest.raises(NotFoundError):
        decisions.save("proj-a", "k", "v", source_message_id=424242)
    with pytest.raises(ValidationError):
        decisions.save("proj-a", "k", "v", source_message_id="7")


def test_valid_source_message_id_preserved(decisions, sample_message_id):
    d = decisions.save(
        "proj-a", "k", "v", source_message_id=sample_message_id, status="approved"
    )
    assert d["source_message_id"] == sample_message_id
    assert d["status"] == "approved"


def test_list_filters_scoped_to_project(decisions):
    decisions.save("proj-a", "use-sqlite", "yes", status="approved")
    decisions.save("proj-a", "old-plan", "no", status="deprecated")
    decisions.save("proj-b", "other", "other")

    all_a = decisions.list_for_project("proj-a")
    assert [d["key"] for d in all_a] == ["old-plan", "use-sqlite"]  # newest first

    live = decisions.list_for_project("proj-a", include_deprecated=False)
    assert [d["key"] for d in live] == ["use-sqlite"]

    approved = decisions.list_for_project("proj-a", status="approved")
    assert [d["key"] for d in approved] == ["use-sqlite"]

    assert decisions.list_for_project("proj-z") == []


def test_get_and_delete_missing_raise(decisions):
    with pytest.raises(NotFoundError):
        decisions.get("proj-a", "missing")
    with pytest.raises(NotFoundError):
        decisions.delete("proj-a", "missing")


def test_project_isolation_decisions(decisions):
    decisions.save("proj-a", "shared-key", "from A")
    decisions.save("proj-b", "shared-key", "from B")
    # proj-a update must not leak into proj-b
    decisions.save("proj-a", "shared-key", "A updated")
    assert decisions.get("proj-b", "shared-key")["value"] == "from B"


def test_foreign_key_enforced_at_db_level(decisions, db_conn):
    """The FK exists; a raw invalid insert fails."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO project_memory"
            " (project, key, value, status, source_message_id, updated_at)"
            " VALUES ('p', 'k', 'v', 'draft', 98765, '2026-01-01T00:00:00Z')"
        )
