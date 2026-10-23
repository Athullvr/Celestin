"""Offline composition tests for the separate hosted HTTP runtime."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from orbit.mcp_server.hosted_auth import Auth0VerifierConfig
from orbit.mcp_server.hosted_server import (
    HostedRuntimeSettings,
    HostedMCPServices,
    HostedDatabasePools,
    PROTECTED_TABLES,
    WorkspaceContextMiddleware,
    _access_token,
    _assert_safe_authorization_reader,
    _assert_safe_project_runtime,
    _workspace_selector,
    create_hosted_mcp_app,
    create_hosted_mcp_server,
    AUTHORIZATION_TABLES,
    HostedRuntimeConfigurationError,
)
from orbit.mcp_server.hosted_scope import (
    HostedAuthorizationUnavailable,
    VerifiedPrincipal,
)
from orbit.mcp_server.server import build_runtime, create_mcp_server
from mcp.server.fastmcp.exceptions import ToolError


ISSUER = "https://celestin-example.auth0.com/"
AUDIENCE = "https://api.celestin.example"
PROJECT_SCOPE = (
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
)
GOOD_CONTROL_ROLE_ROW = (
    False, False, False, False, False,
    True, True, True, True, False,
    True, True, True,
)
GOOD_PROJECT_ROLE_ROW = (
    False, False, False, False, False,
    True, True, True, True, False,
    True, True, True, True, True, False,
    True, True, True, True, True, True, True, True, True, True, True,
)


class FakePool:
    def __init__(
        self,
        row=GOOD_PROJECT_ROLE_ROW,
    ):
        self.row = row
        self.open_calls = 0
        self.open_timeouts = []
        self.close_calls = 0
        self.queries = []
        self.returned_connections = 0

    def open(self, *, wait, timeout=None):
        self.open_calls += 1
        self.open_timeouts.append(timeout)

    def close(self):
        self.close_calls += 1

    def getconn(self, *, timeout):
        self.returned_connections += 1
        return object()

    def putconn(self, _connection):
        self.returned_connections -= 1

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
        authorization_dsn="postgresql://not-a-real-connection",
        project_dsn_env_by_scope={
            PROJECT_SCOPE: "CELESTIN_PROJECT_POSTGRES_DSN_TEST_PROJECT"
        },
        auth=Auth0VerifierConfig(
            ISSUER, AUDIENCE, "auth0", "RS256", "memory:read",
            "memory:write", {"human-client": "human"}
        ),
        public_url="https://celestin.example",
        tls_certfile=cert,
        tls_keyfile=key,
        project_role_isolation_enabled=True,
    )


def fake_pools():
    return HostedDatabasePools(
        FakePool(GOOD_CONTROL_ROLE_ROW),
        {PROJECT_SCOPE: FakePool(GOOD_PROJECT_ROLE_ROW)},
        timeout=1,
    )


def test_hosted_tool_names_and_schemas_match_local_stdio(settings):
    hosted = create_hosted_mcp_server(
        settings, pools=fake_pools(), token_verifier=FakeVerifier()
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
    pools = fake_pools()
    app = create_hosted_mcp_app(settings, pools=pools, token_verifier=FakeVerifier())

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
    assert all(pool.open_calls == pool.close_calls == 0 for pool in pools.all_pools)


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


@pytest.mark.parametrize("index", range(13))
def test_runtime_refuses_unsafe_authorization_reader(index):
    row = list(GOOD_CONTROL_ROLE_ROW)
    row[index] = not row[index]
    with pytest.raises(RuntimeError, match="authorization-reader"):
        _assert_safe_authorization_reader(FakePool(row), timeout=1)


@pytest.mark.parametrize("index", range(27))
def test_runtime_refuses_unsafe_project_role(index):
    row = list(GOOD_PROJECT_ROLE_ROW)
    row[index] = not row[index]
    with pytest.raises(RuntimeError, match="project-isolation"):
        _assert_safe_project_runtime(FakePool(row), timeout=1, scope=PROJECT_SCOPE)


def test_project_runtime_role_probe_checks_scope_and_privilege_invariants():
    pool = FakePool(GOOD_PROJECT_ROLE_ROW)
    _assert_safe_project_runtime(pool, timeout=1, scope=PROJECT_SCOPE)
    assert len(pool.queries) == 1
    assert tuple(PROTECTED_TABLES + AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][2])
    assert tuple(PROTECTED_TABLES) == tuple(pool.queries[0][1][3])
    assert tuple(AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][12])
    assert "relrowsecurity" in pool.queries[0][0]
    assert "relforcerowsecurity" in pool.queries[0][0]
    assert "pg_has_role" in pool.queries[0][0]
    assert "authorization_read_only" in pool.queries[0][0]
    assert "rolreplication" in pool.queries[0][0]
    assert "exact_project_login_mapping" in pool.queries[0][0]
    assert "current_tool_grants" in pool.queries[0][0]
    assert "current_tool_sequence_grants" in pool.queries[0][0]
    assert "no_unexposed_content_grants" in pool.queries[0][0]
    assert "has_any_column_privilege" in pool.queries[0][0]
    assert "safe_scope_mapping_policy" in pool.queries[0][0]


def test_authorization_reader_role_has_no_tenant_content_access():
    pool = FakePool(GOOD_CONTROL_ROLE_ROW)
    _assert_safe_authorization_reader(pool, timeout=1)
    assert tuple(PROTECTED_TABLES + AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][2])
    assert tuple(AUTHORIZATION_TABLES) == tuple(pool.queries[0][1][3])
    assert tuple(PROTECTED_TABLES) == tuple(pool.queries[0][1][4])


def test_project_pool_selection_requires_exact_resolver_scope_and_never_falls_back():
    from orbit.mcp_server.hosted_scope import ResolvedProjectScope

    principal = VerifiedPrincipal("issuer", "subject", "human")
    scope = ResolvedProjectScope._issue(
        principal=principal,
        principal_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        workspace_id=PROJECT_SCOPE[0],
        project_id=PROJECT_SCOPE[1],
        project_key="demo",
        permissions=frozenset({"read"}),
    )
    pools = fake_pools()
    lease = pools.project_connection(scope)
    assert lease._pool is pools.project_pools[PROJECT_SCOPE]
    lease.close()
    assert pools.project_pools[PROJECT_SCOPE].returned_connections == 0

    other_scope = ResolvedProjectScope._issue(
        principal=principal,
        principal_id=scope.principal_id,
        workspace_id=PROJECT_SCOPE[0],
        project_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        project_key="other",
        permissions=frozenset({"read"}),
    )
    with pytest.raises(HostedAuthorizationUnavailable, match="project database is unavailable"):
        pools.project_connection(other_scope)


def test_hosted_settings_require_explicit_isolation_enablement(settings):
    from dataclasses import replace
    from orbit.mcp_server.hosted_server import HostedRuntimeConfigurationError

    with pytest.raises(HostedRuntimeConfigurationError, match="disabled"):
        replace(settings, project_role_isolation_enabled=False)


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
            settings.authorization_dsn,
            settings.project_dsn_env_by_scope,
            settings.auth,
            settings.public_url,
            settings.tls_certfile,
            settings.tls_keyfile,
            project_role_isolation_enabled=True,
            bind_host="0.0.0.0",
        )

    reviewed = HostedRuntimeSettings(
        settings.authorization_dsn,
        settings.project_dsn_env_by_scope,
        settings.auth,
        settings.public_url,
        settings.tls_certfile,
        settings.tls_keyfile,
        project_role_isolation_enabled=True,
        bind_host="0.0.0.0",
        allow_non_loopback=True,
    )
    assert reviewed.bind_host == "0.0.0.0"


def test_public_url_must_match_the_hosted_mcp_origin(settings):
    with pytest.raises(ValueError, match="HTTPS URL"):
        HostedRuntimeSettings(
            settings.authorization_dsn,
            settings.project_dsn_env_by_scope,
            settings.auth,
            settings.public_url + "/unexpected-prefix",
            settings.tls_certfile,
            settings.tls_keyfile,
            project_role_isolation_enabled=True,
        )


def test_database_timeouts_are_bounded_positive_integers(settings):
    with pytest.raises(ValueError, match="timeouts must be positive"):
        HostedRuntimeSettings(
            settings.authorization_dsn,
            settings.project_dsn_env_by_scope,
            settings.auth,
            settings.public_url,
            settings.tls_certfile,
            settings.tls_keyfile,
            project_role_isolation_enabled=True,
            statement_timeout_ms=0,
        )


def test_missing_tls_configuration_is_rejected_without_opening_pool(settings):
    pools = fake_pools()
    with pytest.raises(ValueError, match="TLS certificate"):
        bad = HostedRuntimeSettings(
            settings.authorization_dsn,
            settings.project_dsn_env_by_scope,
            settings.auth,
            settings.public_url,
            settings.tls_certfile.with_name("missing.crt"),
            settings.tls_keyfile,
            project_role_isolation_enabled=True,
        )
        create_hosted_mcp_app(bad, pools=pools, token_verifier=FakeVerifier())
    assert all(pool.open_calls == 0 for pool in pools.all_pools)
