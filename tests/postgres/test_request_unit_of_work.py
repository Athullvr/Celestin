"""Request-bound PostgreSQL adapters share one authorized transaction."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from orbit.mcp_server.hosted_scope import (
    HostedAccessDenied,
    HostedAuthorizationUnavailable,
    HostedSourceMessageNotFound,
    VerifiedPrincipal,
)
from orbit.mcp_server.hosted_identity import HostedRequestBoundary
from orbit.postgres.authorization import PostgresHostedAuthorizationSessionFactory
from orbit.postgres.unit_of_work import PostgresRequestUnitOfWork
from orbit.retrieval.postgres_data import PostgresRetrievalData
from orbit.storage.postgres import PostgresMemoryStore


WORKSPACE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
USER = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
MESSAGE_ID = 41
NOW = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, row=None, rows=()):
        self.row = row
        self.rows = list(rows)
        self.closed = False

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, *, project_archived=None, workspace_archived=None,
                 grant=(True, True, None), message_id=MESSAGE_ID,
                 fail_on=None):
        self.project_archived = project_archived
        self.workspace_archived = workspace_archived
        self.grant = grant
        self.message_id = message_id
        self.fail_on = fail_on
        self.queries = []
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0
        self.close_calls = 0
        self.closed = False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.queries.append((sql, tuple(params)))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("private database detail")

        if sql.startswith("SELECT id FROM celestin_workspaces"):
            row = (WORKSPACE,)
            rows = ()
        elif sql.startswith("SELECT id, status FROM celestin_users"):
            row, rows = (USER, "active"), ()
        elif sql.startswith("SELECT archived_at FROM celestin_workspaces"):
            row, rows = (self.workspace_archived,), ()
        elif sql.startswith("SELECT id, legacy_project_key, archived_at"):
            row, rows = (PROJECT, "demo", self.project_archived), ()
        elif sql.startswith("SELECT status FROM celestin_workspace_memberships"):
            row, rows = ("active",), ()
        elif sql.startswith("SELECT can_read, can_write, revoked_at FROM celestin_project_memberships"):
            row, rows = self.grant, ()
        elif sql.startswith("SELECT id FROM chat_messages"):
            row, rows = ((self.message_id,) if self.message_id is not None else None), ()
        elif sql.startswith("INSERT INTO chat_messages"):
            row, rows = (81, NOW), ()
        elif sql.startswith("SELECT 1 FROM chat_messages"):
            row, rows = ((1,) if self.message_id is not None else None), ()
        elif sql.startswith("INSERT INTO project_memory"):
            row, rows = (91, "draft", MESSAGE_ID, NOW, NOW, "topic", "value"), ()
        elif "FROM chat_messages AS record" in sql:
            row, rows = None, [(81, "synthetic memory", NOW, "conversation", 0.7)]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

        cursor = Result(row, rows)
        self.cursors.append(cursor)
        return cursor

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def close(self):
        self.close_calls += 1
        self.closed = True


class WorkspaceBinding:
    def workspace_for(self, principal):
        return WORKSPACE


class StatusProvider:
    def is_active(self, principal):
        return True


def build_request(connection):
    connect_calls = []

    def connect():
        connect_calls.append(connection)
        return connection

    factory = PostgresHostedAuthorizationSessionFactory(connect)
    return factory, connect_calls


class Authenticator:
    def authenticate(self, _transport_context):
        return PRINCIPAL


def request_boundary(factory):
    return HostedRequestBoundary(
        authenticator=Authenticator(),
        workspace_binding=WorkspaceBinding(),
        principal_status=StatusProvider(),
        request_executor=factory,
    )


def execute_request(factory, project, action, operation, *, source_message_id=None):
    return request_boundary(factory).execute_authorized_request(
        object(),
        project,
        action,
        operation,
        source_message_id=source_message_id,
    )


PRINCIPAL = VerifiedPrincipal("issuer", "subject", "human")


def test_authorized_memory_and_retrieval_share_one_connection_and_commit_once():
    connection = Connection()
    factory, connect_calls = build_request(connection)

    def operation(request):
        assert request.memory_store._request_connection is connection
        assert request.retrieval_data._request_connection is connection
        assert not hasattr(request, "authorization_session")
        assert not hasattr(request, "scope")
        assert not hasattr(request, "connection")

        message = request.memory_store.insert_message(
            "demo", "conversation", "user", "synthetic memory"
        )
        decision = request.memory_store.save_decision(
            "demo", "topic", "value", message.message_id
        )
        results = request.retrieval_service.search_chat_history(
            "demo", "synthetic memory", 5
        )
        assert message.message_id == "81"
        assert decision.decision_id == "91"
        assert results[0].message_id == "81"
        assert not connection.commits and not connection.rollbacks
        assert not connection.closed and connection.close_calls == 0
        return "complete"

    result = execute_request(factory, "demo", "write", operation)

    assert result == "complete"
    assert connect_calls == [connection]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.close_calls == 1 and connection.closed
    assert any("INSERT INTO chat_messages" in sql for sql, _ in connection.queries)
    assert any("INSERT INTO project_memory" in sql for sql, _ in connection.queries)
    assert any("FROM chat_messages AS record" in sql for sql, _ in connection.queries)
    assert all(
        "record.workspace_id = %s::uuid" in sql
        and "record.project_id = %s::uuid" in sql
        for sql, _ in connection.queries
        if "FROM chat_messages AS record" in sql
    )


def test_later_operation_failure_rolls_back_prior_write_and_closes_without_commit():
    connection = Connection(fail_on="FROM chat_messages AS record")
    factory, connect_calls = build_request(connection)

    with pytest.raises(HostedAuthorizationUnavailable) as error:
        execute_request(
            factory,
            "demo",
            "write",
            lambda request: (
                request.memory_store.insert_message(
                    "demo", "conversation", "user", "synthetic"
                ),
                request.retrieval_service.search_chat_history("demo", "synthetic", 5),
            ),
        )

    assert "private database detail" not in str(error.value)
    assert connect_calls == [connection]
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.close_calls == 1 and connection.closed
    assert any("INSERT INTO chat_messages" in sql for sql, _ in connection.queries)


def test_read_only_scope_cannot_write_and_project_mismatch_does_not_query():
    connection = Connection(grant=(True, False, None))
    factory, _ = build_request(connection)

    def operation(request):
        before = len(connection.queries)
        with pytest.raises(HostedAccessDenied, match="access denied"):
            request.memory_store.insert_message(
                "demo", "conversation", "user", "synthetic"
            )
        with pytest.raises(HostedAccessDenied, match="access denied"):
            request.memory_store.insert_message(
                "other-project", "conversation", "user", "synthetic"
            )
        with pytest.raises(ValueError, match="trusted retrieval scope"):
            request.retrieval_data.search_messages(
                "other-project", "query", 5, relax=False
            )
        assert len(connection.queries) == before

    execute_request(factory, "demo", "read", operation)
    assert not any("INSERT INTO chat_messages" in sql for sql, _ in connection.queries)
    assert connection.commits == 1 and connection.close_calls == 1


@pytest.mark.parametrize(
    "connection",
    [Connection(project_archived=NOW), Connection(workspace_archived=NOW),
     Connection(message_id=None)],
    ids=["archived-project", "archived-workspace", "missing-source"],
)
def test_archived_scope_or_missing_source_denies_before_operation(connection):
    factory, _ = build_request(connection)
    called = False

    def operation(request):
        nonlocal called
        called = True

    kwargs = {"source_message_id": str(MESSAGE_ID)} if connection.message_id is None else {}
    with pytest.raises((
        HostedAccessDenied,
        HostedAuthorizationUnavailable,
        HostedSourceMessageNotFound,
    )):
        execute_request(factory, "demo", "write", operation, **kwargs)
    assert not called
    assert connection.rollbacks == 1 and connection.close_calls == 1
    assert connection.commits == 0


def test_source_validation_uses_workspace_and_project_ids_before_operation():
    connection = Connection()
    factory, _ = build_request(connection)
    called = False

    def operation(request):
        nonlocal called
        called = True

    execute_request(
        factory,
        "demo",
        "write",
        operation,
        source_message_id=str(MESSAGE_ID),
    )
    source_query, params = next(
        (sql, params) for sql, params in connection.queries
        if sql.startswith("SELECT id FROM chat_messages")
    )
    assert "workspace_id = %s" in source_query and "project_id = %s" in source_query
    assert params == (WORKSPACE, PROJECT, MESSAGE_ID)
    assert called


def test_request_uow_cannot_be_constructed_with_standalone_adapters(monkeypatch):
    connection = Connection()
    factory, _connect_calls = build_request(connection)

    def forbidden(*_args, **_kwargs):
        pytest.fail("standalone PostgreSQL adapters must not be selected by request composition")

    monkeypatch.setattr(PostgresMemoryStore, "from_dsn", classmethod(forbidden))
    monkeypatch.setattr(PostgresRetrievalData, "from_dsn", classmethod(forbidden))
    with pytest.raises(TypeError):
        PostgresRequestUnitOfWork(
            object(), object(), PostgresMemoryStore, PostgresRetrievalData,
            object(), object(),
        )

    result = execute_request(factory, "demo", "read", lambda request: request.retrieval_data)
    assert isinstance(result, PostgresRetrievalData)
    assert connection.commits == 1 and connection.close_calls == 1


def test_request_factory_has_no_public_executor_and_missing_auth_never_connects():
    connection = Connection()
    factory, connect_calls = build_request(connection)
    assert not hasattr(factory, "execute_authorized")
    assert not hasattr(factory, "execute_authorized_request")
    assert not hasattr(factory, "transaction")

    boundary = HostedRequestBoundary(
        authenticator=None,
        workspace_binding=WorkspaceBinding(),
        principal_status=StatusProvider(),
        request_executor=factory,
    )
    with pytest.raises(HostedAuthorizationUnavailable, match="authentication is not configured"):
        boundary.execute_authorized_request(
            object(), "demo", "read", lambda _request: pytest.fail("must not run")
        )
    assert connect_calls == []
    assert connection.queries == []
