"""Offline composition tests for the separate hosted HTTP runtime."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import httpx
import pytest

from orbit.mcp_server.hosted_auth import Auth0VerifierConfig
from orbit.mcp_server.hosted_server import (
    HostedRuntimeSettings,
    HostedMCPServices,
    PROTECTED_TABLES,
    WorkspaceContextMiddleware,
    _access_token,
    _assert_safe_runtime_role,
    _workspace_selector,
    create_hosted_mcp_app,
    create_hosted_mcp_server,
    AUTHORIZATION_TABLES,
)
from orbit.mcp_server.server import build_runtime, create_mcp_server
from mcp.server.fastmcp.exceptions import ToolError


ISSUER = "https://celestin-example.auth0.com/"
AUDIENCE = "https://api.celestin.example"
GOOD_RUNTIME_ROLE_ROW = (
    False, False, False, False, False,
    True, True, True, True,
    False, False, False,
    True, True, True, True, True, True,
)


class FakePool:
    def __init__(
        self,
        row=GOOD_RUNTIME_ROLE_ROW,
    ):
        self.row = row
        self.open_calls = 0
        self.open_timeouts = []
        self.close_calls = 0
        self.queries = []

    def open(self, *, wait, timeout=None):
        self.open_calls += 1
        self.open_timeouts.append(timeout)

    def close(self):
        self.close_calls += 1

    @contextmanager
    def connection(self, *, timeout):
        pool = self

        class Connection:
            def execute(self, query, params):
                pool.queries.append((query, params))
                return Cursor(pool.row)

        yield Connection()


class Cursor:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class FakeVerifier:
    async def verify_token(self, token):
        return None


@pytest.fixture
def settings(tmp_path):
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("test certificate path only", encoding="utf-8")
    key.write_text("test private key path only", encoding="utf-8")
    return HostedRuntimeSettings(
        postgres_dsn="postgresql://not-a-real-connection",
        auth=Auth0VerifierConfig(
            ISSUER, AUDIENCE, "auth0", "RS256", "memory:read",
            "memory:write", {"human-client": "human"}
        ),
        public_url="https://celestin.example",
        tls_certfile=cert,
        tls_keyfile=key,
    )


def test_hosted_tool_names_and_schemas_match_local_stdio(settings):
    hosted = create_hosted_mcp_server(
        settings, pool=FakePool(), token_verifier=FakeVerifier()
    )
    local = create_mcp_server(build_runtime(db_path=":memory:"))

    local_tools = {tool.name: tool for tool in local._tool_manager.list_tools()}
    hosted_tools = {tool.name: tool for tool in hosted._tool_manager.list_tools()}
    assert set(hosted_tools) == set(local_tools) == {
        "ingest_chat_message", "save_decision", "search_chat_history",
        "retrieve_context", "ping",
    }
    for name in local_tools:
        assert hosted_tools[name].parameters == local_tools[name].parameters
        assert hosted_tools[name].fn_metadata.output_schema == local_tools[name].fn_metadata.output_schema
        assert hosted_tools[name].description == local_tools[name].description


def test_hosted_app_health_is_public_but_mcp_requires_a_bearer_token(settings):
    pool = FakePool()
    app = create_hosted_mcp_app(settings, pool=pool, token_verifier=FakeVerifier())

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            health = await client.get("/healthz")
            protected = await client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
            )
            return health, protected

    health, protected = asyncio.run(request())
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert protected.status_code == 401
    assert pool.open_calls == pool.close_calls == 0


def test_workspace_context_is_request_local_and_preserves_duplicate_headers():
    observed = []

    class App:
        async def __call__(self, scope, receive, send):
            observed.append(_workspace_selector.get())

    app = WorkspaceContextMiddleware(App())

    async def invoke(values):
        scope = {
            "type": "http",
            "headers": [(b"x-celestin-workspace-id", value) for value in values],
        }
        await app(scope, None, None)

    asyncio.run(invoke([b"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]))
    asyncio.run(invoke([
        b"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        b"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ]))
    assert observed == [
        ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",),
        (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        ),
    ]
    assert _workspace_selector.get() is None


@pytest.mark.parametrize(
    "index,value",
    [
        (0, True), (1, True), (2, True), (3, True), (4, True),
        (5, False), (6, False), (7, False), (8, False),
        (9, True), (10, True), (11, True),
        (12, False), (13, False), (14, False), (15, False),
        (16, False), (17, False),
    ],
)
def test_runtime_refuses_unsafe_role_or_incomplete_privileges(index, value):
    row = list(GOOD_RUNTIME_ROLE_ROW)
    row[index] = value
    with pytest.raises(RuntimeError, match="least-privilege/RLS"):
        _assert_safe_runtime_role(FakePool(row), timeout=1)


def test_runtime_role_probe_checks_all_content_tables():
    pool = FakePool()
    _assert_safe_runtime_role(pool, timeout=1)
    assert len(pool.queries) == 1
    assert tuple(PROTECTED_TABLES + AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][0])
    assert tuple(PROTECTED_TABLES) == tuple(pool.queries[0][1][1])
    assert tuple(AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][7])
    assert "relrowsecurity" in pool.queries[0][0]
    assert "relforcerowsecurity" in pool.queries[0][0]
    assert "pg_has_role" in pool.queries[0][0]
    assert "authorization_tables_are_read_only" in pool.queries[0][0]
    assert "rolreplication" in pool.queries[0][0]
    assert "can_evaluate_request_scope" in pool.queries[0][0]
    assert "can_run_current_memory_tools" in pool.queries[0][0]
    assert "can_allocate_memory_ids" in pool.queries[0][0]
    assert "no_unexposed_tenant_table_privileges" in pool.queries[0][0]
    assert "has_any_column_privilege" in pool.queries[0][0]


def test_api_scope_denial_occurs_before_request_database_boundary():
    class Boundary:
        called = False

        def execute_authorized_request(self, *args, **kwargs):
            self.called = True
            raise AssertionError("database boundary must not be called")

    boundary = Boundary()
    services = HostedMCPServices(
        boundary, read_scope="memory:read", write_scope="memory:write"
    )
    token = _access_token.set(type("Token", (), {"scopes": ["memory:read"]})())
    try:
        with pytest.raises(ToolError, match="ACCESS_DENIED"):
            services.ingest_chat_message("project", "conversation", "user", "text")
    finally:
        _access_token.reset(token)
    assert not boundary.called


def test_hosted_operation_scope_mapping_cannot_be_reconfigured():
    with pytest.raises(ValueError, match="memory:read and memory:write"):
        HostedMCPServices(object(), read_scope="read", write_scope="write")


def test_non_loopback_host_requires_explicit_deployment_opt_in(settings):
    with pytest.raises(ValueError, match="binds to loopback"):
        HostedRuntimeSettings(
            settings.postgres_dsn,
            settings.auth,
            settings.public_url,
            settings.tls_certfile,
            settings.tls_keyfile,
            bind_host="0.0.0.0",
        )

    reviewed = HostedRuntimeSettings(
        settings.postgres_dsn,
        settings.auth,
        settings.public_url,
        settings.tls_certfile,
        settings.tls_keyfile,
        bind_host="0.0.0.0",
        allow_non_loopback=True,
    )
    assert reviewed.bind_host == "0.0.0.0"


def test_public_url_must_match_the_hosted_mcp_origin(settings):
    with pytest.raises(ValueError, match="HTTPS URL"):
        HostedRuntimeSettings(
            settings.postgres_dsn,
            settings.auth,
            settings.public_url + "/unexpected-prefix",
            settings.tls_certfile,
            settings.tls_keyfile,
        )


def test_database_timeouts_are_bounded_positive_integers(settings):
    with pytest.raises(ValueError, match="timeouts must be positive"):
        HostedRuntimeSettings(
            settings.postgres_dsn,
            settings.auth,
            settings.public_url,
            settings.tls_certfile,
            settings.tls_keyfile,
            statement_timeout_ms=0,
        )


def test_missing_tls_configuration_is_rejected_without_opening_pool(settings):
    pool = FakePool()
    with pytest.raises(ValueError, match="TLS certificate"):
        bad = HostedRuntimeSettings(
            settings.postgres_dsn,
            settings.auth,
            settings.public_url,
            settings.tls_certfile.with_name("missing.crt"),
            settings.tls_keyfile,
        )
        create_hosted_mcp_app(bad, pool=pool, token_verifier=FakeVerifier())
    assert pool.open_calls == 0
