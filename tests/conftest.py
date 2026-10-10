"""Shared pytest fixtures: an isolated temp SQLite database per test."""

from __future__ import annotations

import pytest

from memory_bridge.database.engine import connect


@pytest.fixture()
def db_conn(tmp_path):
    return connect(tmp_path / "test.db")


@pytest.fixture()
def messages(db_conn):
    from memory_bridge.repositories.messages import ChatMessageRepository

    return ChatMessageRepository(db_conn)


@pytest.fixture()
def decisions(db_conn):
    from memory_bridge.repositories.decisions import DecisionRepository

    return DecisionRepository(db_conn)


@pytest.fixture()
def sample_message_id(db_conn, messages) -> int:
    return messages.insert(
        project="proj-a", conversation_id="conv-1", role="user", content="hi"
    )
