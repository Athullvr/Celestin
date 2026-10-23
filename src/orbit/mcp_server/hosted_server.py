"""Separately configured Auth0/PostgreSQL Streamable HTTP MCP runtime.

The local ``celestin``/``orbit``/``memory-bridge`` entry points remain the
existing stdio/SQLite server. This module is imported only by the explicit
``celestin-hosted`` command.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from orbit.mcp_server.hosted_auth import (
    Auth0AccessTokenAuthenticator,
    Auth0TokenVerifier,
    Auth0VerifierConfig,
    READ_SCOPE,
    WRITE_SCOPE,
)
from orbit.mcp_server.hosted_identity import HostedRequestBoundary
from orbit.mcp_server.hosted_scope import (
    HostedAccessDenied,
    HostedAuthorizationUnavailable,
    HostedSourceMessageNotFound,
    PrincipalStatusProvider,
    VerifiedPrincipal,
    WorkspaceBinding,
)
from orbit.postgres.authorization import PostgresHostedAuthorizationSessionFactory
from orbit.postgres.unit_of_work import PostgresRequestUnitOfWork
from orbit.retrieval.service import _search_result_dict

from .server import (
    MCPToolHandlers,
    register_mcp_tools,
    _error,
)


logger = logging.getLogger(__name__)
_workspace_selector: ContextVar[object] = ContextVar(
    "celestin_hosted_workspace_selector", default=None
)
_access_token: ContextVar[object] = ContextVar("celestin_hosted_access_token", default=None)
WORKSPACE_HEADER = b"x-celestin-workspace-id"
PROTECTED_TABLES = (
    "chat_messages",
    "project_memory",
    "celestin_knowledge_records",
    "celestin_evidence_records",
    "celestin_project_producers",
    "celestin_project_source_namespaces",
    "celestin_candidates",
    "celestin_candidate_revisions",
    "celestin_candidate_review_events",
    "celestin_candidate_evidence_records",
    "celestin_candidate_occurrences",
    "celestin_candidate_conversions",
)
AUTHORIZATION_TABLES = (
    "celestin_users",
    "celestin_workspaces",
    "celestin_workspace_memberships",
    "celestin_projects",
    "celestin_project_memberships",
    "celestin_service_identities",
    "celestin_service_project_grants",
    "celestin_schema_migrations",
)


class HostedRuntimeConfigurationError(ValueError):
    """Hosted mode is missing a required non-secret configuration value."""


@dataclass(frozen=True, slots=True)
class HostedRuntimeSettings:
    postgres_dsn: str
    auth: Auth0VerifierConfig
    public_url: str
    tls_certfile: Path
    tls_keyfile: Path
    bind_host: str = "127.0.0.1"
    port: int = 8765
    pool_min_size: int = 1
    pool_max_size: int = 10
    pool_timeout: float = 5.0
    connection_timeout: int = 5
    statement_timeout_ms: int = 10_000
    allow_non_loopback: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.postgres_dsn, str) or not self.postgres_dsn.strip():
            raise HostedRuntimeConfigurationError("CELESTIN_POSTGRES_DSN is required.")
        public = urlsplit(self.public_url)
        if (
            public.scheme != "https" or not public.hostname
            or public.username is not None or public.password is not None
            or public.path not in ("", "/") or public.query or public.fragment
        ):
            raise HostedRuntimeConfigurationError(
                "CELESTIN_HOSTED_PUBLIC_URL must be an HTTPS URL without credentials, query, or fragment."
            )
        if not self.tls_certfile.is_file() or not self.tls_keyfile.is_file():
            raise HostedRuntimeConfigurationError(
                "Hosted mode requires readable TLS certificate and key files."
            )
        if not isinstance(self.bind_host, str) or not self.bind_host.strip():
            raise HostedRuntimeConfigurationError("Hosted bind address is invalid.")
        if type(self.allow_non_loopback) is not bool:
            raise HostedRuntimeConfigurationError("Non-loopback bind approval must be an explicit boolean.")
        if not self.allow_non_loopback and not _is_loopback_bind(self.bind_host):
            raise HostedRuntimeConfigurationError(
                "Hosted mode binds to loopback unless a reviewed deployment explicitly enables non-loopback binding."
            )
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise HostedRuntimeConfigurationError("Hosted port must be between 1 and 65535.")
        if (
            isinstance(self.pool_min_size, bool) or not isinstance(self.pool_min_size, int)
            or isinstance(self.pool_max_size, bool) or not isinstance(self.pool_max_size, int)
            or self.pool_min_size < 0 or self.pool_max_size < 1
            or self.pool_min_size > self.pool_max_size
        ):
            raise HostedRuntimeConfigurationError("PostgreSQL pool size configuration is invalid.")
        if (
            isinstance(self.connection_timeout, bool)
            or not isinstance(self.connection_timeout, int)
            or self.connection_timeout < 1
            or isinstance(self.statement_timeout_ms, bool)
            or not isinstance(self.statement_timeout_ms, int)
            or self.statement_timeout_ms < 1
        ):
            raise HostedRuntimeConfigurationError("PostgreSQL connection/query timeouts must be positive integers.")

    @classmethod
    def from_environment(cls) -> HostedRuntimeSettings:
        def positive_int(name: str, default: int) -> int:
            raw = os.environ.get(name, str(default))
            try:
                value = int(raw)
            except (ValueError, TypeError):
                raise HostedRuntimeConfigurationError(f"{name} must be an integer.") from None
            return value

        raw_timeout = os.environ.get("CELESTIN_HOSTED_DB_POOL_TIMEOUT", "5")
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            raise HostedRuntimeConfigurationError(
                "CELESTIN_HOSTED_DB_POOL_TIMEOUT must be a positive number."
            ) from None
        if timeout <= 0:
            raise HostedRuntimeConfigurationError(
                "CELESTIN_HOSTED_DB_POOL_TIMEOUT must be a positive number."
            )
        dsn = os.environ.get("CELESTIN_POSTGRES_DSN", "")
        public_url = os.environ.get("CELESTIN_HOSTED_PUBLIC_URL", "")
        cert = os.environ.get("CELESTIN_HOSTED_TLS_CERTFILE", "")
        key = os.environ.get("CELESTIN_HOSTED_TLS_KEYFILE", "")
        if not dsn or not public_url or not cert or not key:
            raise HostedRuntimeConfigurationError(
                "Hosted mode requires the PostgreSQL DSN, public HTTPS URL, and TLS certificate/key paths."
            )
        return cls(
            postgres_dsn=dsn,
            auth=Auth0VerifierConfig.from_environment(),
            public_url=public_url,
            tls_certfile=Path(cert),
            tls_keyfile=Path(key),
            bind_host=os.environ.get("CELESTIN_HOSTED_BIND", "127.0.0.1"),
            port=positive_int("CELESTIN_HOSTED_PORT", 8765),
            pool_min_size=positive_int("CELESTIN_HOSTED_DB_POOL_MIN_SIZE", 1),
            pool_max_size=positive_int("CELESTIN_HOSTED_DB_POOL_MAX_SIZE", 10),
            pool_timeout=timeout,
            connection_timeout=positive_int("CELESTIN_HOSTED_DB_CONNECT_TIMEOUT", 5),
            statement_timeout_ms=positive_int("CELESTIN_HOSTED_DB_STATEMENT_TIMEOUT_MS", 10_000),
            allow_non_loopback=os.environ.get("CELESTIN_HOSTED_ALLOW_NON_LOOPBACK", "false").lower() == "true",
        )


class ExplicitWorkspaceBinding(WorkspaceBinding):
    """Return only the explicit request selector; PostgreSQL validates access."""

    def workspace_for(
        self,
        principal: VerifiedPrincipal,
        requested_workspace_id=None,
    ):
        if not isinstance(principal, VerifiedPrincipal):
            return None
        return requested_workspace_id


class _DatabasePrincipalStatus(PrincipalStatusProvider):
    """Force principal status to be resolved by the request's locked PG session."""

    def is_active(self, principal: VerifiedPrincipal) -> bool:
        return False


class _PoolConnectionLease:
    """A closeable request lease whose close returns it to psycopg_pool."""

    def __init__(self, pool, timeout: float) -> None:
        self._pool = pool
        self._connection = pool.getconn(timeout=timeout)
        self._closed = False

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pool.putconn(self._connection)


class HostedMCPServices:
    """Existing MCP operations composed through Auth0, PostgreSQL and one UoW."""

    def __init__(
        self,
        boundary: HostedRequestBoundary,
        *,
        read_scope: str,
        write_scope: str,
    ) -> None:
        if read_scope != READ_SCOPE or write_scope != WRITE_SCOPE:
            raise ValueError("Hosted MCP scope mapping must use memory:read and memory:write.")
        self._boundary = boundary
        self._required_scopes = {"read": READ_SCOPE, "write": WRITE_SCOPE}

    def _execute(self, project: str, action: str, operation, *, source_message_id=None):
        token = _access_token.get()
        required_scope = self._required_scopes[action]
        if token is None or required_scope not in getattr(token, "scopes", ()):
            raise _error("ACCESS_DENIED", "Access to this project is not permitted.")
        try:
            return self._boundary.execute_authorized_request(
                token,
                project,
                action,
                operation,
                workspace_selector=_workspace_selector.get(),
                source_message_id=source_message_id,
            )
        except HostedAccessDenied:
            raise _error("ACCESS_DENIED", "Access to this project is not permitted.") from None
        except HostedSourceMessageNotFound:
            raise _error(
                "SOURCE_MESSAGE_NOT_FOUND",
                "The source message was not found in this project.",
            ) from None
        except HostedAuthorizationUnavailable:
            logger.error("hosted authorization or database request failed")
            raise _error("STORAGE_ERROR", "The request could not be completed.") from None
        except Exception as exc:
            logger.error("hosted operation failed (%s)", type(exc).__name__)
            code = "RETRIEVAL_UNAVAILABLE" if action == "read" else "STORAGE_ERROR"
            message = "The retrieval service is unavailable." if action == "read" else "The request could not be completed."
            raise _error(code, message) from None

    def ingest_chat_message(self, project: str, conversation_id: str, role: str, content: str):
        def operation(request: PostgresRequestUnitOfWork):
            message = request.memory_store.insert_message(project, conversation_id, role, content)
            return {
                "project": message.project,
                "message_id": message.message_id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }

        return self._execute(project, "write", operation)

    def save_decision(self, project: str, key: str, value: str, source_message_id: str):
        def operation(request: PostgresRequestUnitOfWork):
            decision = request.memory_store.save_decision(
                project, key, value, source_message_id, status="draft"
            )
            return {
                "project": decision.project,
                "decision_id": decision.decision_id,
                "key": decision.key,
                "value": decision.value,
                "status": decision.status,
                "source_message_id": decision.source_message_id,
                "created_at": decision.created_at,
                "updated_at": decision.updated_at,
            }

        return self._execute(
            project,
            "write",
            operation,
            source_message_id=source_message_id,
        )

    def search_chat_history(self, project: str, query: str, limit: int):
        def operation(request: PostgresRequestUnitOfWork):
            results = request.retrieval_service.search_chat_history(project, query, limit)
            return {
                "project": project,
                "query": query,
                "results": [_search_result_dict(result) for result in results],
            }

        return self._execute(project, "read", operation)

    def retrieve_context(self, project: str, query: str, token_budget: int):
        def operation(request: PostgresRequestUnitOfWork):
            service = request.retrieval_service
            bundle = service.retrieve_context(project, query, token_budget)

            def public_record(record: Any) -> dict[str, Any]:
                source_message_id = (
                    record.record_id
                    if record.record_kind == "chat_message"
                    else record.source_id
                )
                source = service.last_sources.get(record.record_id)
                if source is not None:
                    source_message_id = None
                result = {
                    "record_id": record.record_id,
                    "source_message_id": source_message_id,
                    "created_at": record.timestamp,
                    "record_kind": record.record_kind,
                    "status": record.status,
                }
                if source is not None:
                    result["source"] = source
                if hasattr(record, "content"):
                    result["content"] = record.content
                return result

            response = {
                "project": project,
                "query": query,
                "items": [
                    {**public_record(item), "relevance_score": item.relevance_score}
                    for item in bundle.items
                ],
                "rendered_context": bundle.rendered_context,
                "token_count": bundle.token_count,
                "token_budget": bundle.token_budget,
                "token_count_is_estimate": bundle.token_count_is_estimate,
                "token_counter": bundle.token_counter,
                "excluded": [
                    {**public_record(item), "reason": item.reason}
                    for item in bundle.excluded
                    if item.reason in {"token_budget", "duplicate_content"}
                ],
            }
            if service.semantic_enabled or service.documents_enabled:
                response["retrieval"] = service.last_retrieval.as_dict()
            return response

        return self._execute(project, "read", operation)


@dataclass(frozen=True, slots=True)
class _HandlerRuntime:
    persistence: HostedMCPServices
    retrieval: HostedMCPServices


class HostedMCPToolHandlers:
    """Async HTTP wrappers that reuse local validation and public MCP schemas."""

    def __init__(self, services: HostedMCPServices) -> None:
        self._handlers = MCPToolHandlers(_HandlerRuntime(services, services))

    async def _call(self, handler, *args):
        token = _access_token.set(get_access_token())
        try:
            return await asyncio.to_thread(handler, *args)
        finally:
            _access_token.reset(token)

    async def ingest_chat_message(
        self, project: str, conversation_id: str, role: str, content: str
    ) -> dict[str, Any]:
        return await self._call(
            self._handlers.ingest_chat_message, project, conversation_id, role, content
        )

    async def save_decision(
        self, project: str, key: str, value: str, source_message_id: str
    ) -> dict[str, Any]:
        return await self._call(
            self._handlers.save_decision, project, key, value, source_message_id
        )

    async def search_chat_history(
        self, project: str, query: str, limit: int = 10
    ) -> dict[str, Any]:
        return await self._call(self._handlers.search_chat_history, project, query, limit)

    async def retrieve_context(
        self, project: str, query: str, token_budget: int
    ) -> dict[str, Any]:
        return await self._call(
            self._handlers.retrieve_context, project, query, token_budget
        )

    async def ping(self) -> str:
        return await self._call(self._handlers.ping)


class WorkspaceContextMiddleware:
    """Carry the untrusted explicit workspace header in request-local context."""

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        values = tuple(
            value.decode("ascii", errors="replace")
            for name, value in scope.get("headers", ())
            if name.lower() == WORKSPACE_HEADER
        )
        token = _workspace_selector.set(values if values else None)
        try:
            await self._app(scope, receive, send)
        finally:
            _workspace_selector.reset(token)


def create_hosted_mcp_app(
    settings: HostedRuntimeSettings,
    *,
    pool=None,
    token_verifier=None,
):
    """Compose an HTTPS-only Streamable HTTP app; construction does no DB I/O."""
    mcp = create_hosted_mcp_server(
        settings, pool=pool, token_verifier=token_verifier
    )
    return WorkspaceContextMiddleware(mcp.streamable_http_app())


def create_hosted_mcp_server(
    settings: HostedRuntimeSettings,
    *,
    pool=None,
    token_verifier=None,
) -> FastMCP:
    """Build the authenticated hosted FastMCP composition without opening DB I/O."""
    if pool is None:
        pool = _create_pool(settings)
    verifier = token_verifier or Auth0TokenVerifier(settings.auth)
    session_factory = PostgresHostedAuthorizationSessionFactory(
        lambda: _PoolConnectionLease(pool, settings.pool_timeout),
        statement_timeout_ms=settings.statement_timeout_ms,
    )
    boundary = HostedRequestBoundary(
        authenticator=Auth0AccessTokenAuthenticator(),
        workspace_binding=ExplicitWorkspaceBinding(),
        principal_status=_DatabasePrincipalStatus(),
        request_executor=session_factory,
    )
    services = HostedMCPServices(
        boundary,
        read_scope=settings.auth.read_scope,
        write_scope=settings.auth.write_scope,
    )

    @asynccontextmanager
    async def lifespan(_server):
        await asyncio.to_thread(pool.open, wait=True, timeout=settings.pool_timeout)
        try:
            await asyncio.to_thread(_assert_safe_runtime_role, pool, settings.pool_timeout)
            yield
        finally:
            await asyncio.to_thread(pool.close)

    mcp = FastMCP(
        "Celestin Hosted",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=settings.auth.issuer_url,
            resource_server_url=f"{settings.public_url.rstrip('/')}/mcp",
            validate_token_resource=False,
        ),
        host=settings.bind_host,
        port=settings.port,
        streamable_http_path="/mcp",
        max_request_body_size=2_097_152,
        lifespan=lifespan,
    )
    handlers = HostedMCPToolHandlers(services)
    register_mcp_tools(mcp, handlers)

    async def healthz(_request: Request):
        return JSONResponse({"status": "ok"})

    async def readyz(_request: Request):
        try:
            await asyncio.to_thread(_assert_safe_runtime_role, pool, settings.pool_timeout)
        except Exception as exc:
            logger.error("hosted readiness check failed (%s)", type(exc).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)(healthz)
    mcp.custom_route("/readyz", methods=["GET"], include_in_schema=False)(readyz)
    return mcp


def _create_pool(settings: HostedRuntimeSettings):
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:  # pragma: no cover - optional hosted extra
        raise RuntimeError(
            "Hosted PostgreSQL runtime requires the hosted optional dependencies."
        ) from exc
    return ConnectionPool(
        conninfo=settings.postgres_dsn,
        kwargs={"connect_timeout": settings.connection_timeout},
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        timeout=settings.pool_timeout,
        open=False,
    )


def _is_loopback_bind(host: str) -> bool:
    import ipaddress

    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _assert_safe_runtime_role(pool, timeout: float) -> None:
    query = """
        SELECT role.rolsuper, role.rolbypassrls,
               role.rolcreaterole, role.rolcreatedb,
               EXISTS (
                   SELECT 1
                     FROM pg_catalog.pg_class AS relation
                     JOIN pg_catalog.pg_namespace AS namespace
                       ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY(%s)
                      AND relation.relowner = role.oid
               ) AS owns_protected_table,
               (
                   SELECT count(*) = cardinality(%s::text[])
                     FROM pg_catalog.pg_class AS relation
                     JOIN pg_catalog.pg_namespace AS namespace
                       ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY(%s)
                      AND relation.relkind IN ('r', 'p')
                      AND relation.relrowsecurity
                      AND relation.relforcerowsecurity
               ) AS all_tables_force_rls,
               (
                   SELECT count(policy.oid) = cardinality(%s::text[])
                      AND count(policy.oid) FILTER (
                          WHERE policy.polcmd = '*'
                            AND pg_catalog.pg_get_expr(policy.polqual, policy.polrelid)
                                LIKE '%celestin_request_scope_matches%'
                            AND pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
                                LIKE '%celestin_request_scope_matches%'
                      ) = cardinality(%s::text[])
                     FROM pg_catalog.pg_class AS relation
                     JOIN pg_catalog.pg_namespace AS namespace
                       ON namespace.oid = relation.relnamespace
                     JOIN pg_catalog.pg_policy AS policy
                       ON policy.polrelid = relation.oid
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY(%s)
               ) AS all_tables_have_scope_policy,
               NOT EXISTS (
                   SELECT 1
                     FROM unnest(%s::text[]) AS protected(table_name)
                    WHERE has_table_privilege(
                              current_user,
                              format('public.%I', protected.table_name),
                              'DELETE'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', protected.table_name),
                              'TRUNCATE'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', protected.table_name),
                              'TRIGGER'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', protected.table_name),
                              'REFERENCES'
                          )
               ) AS no_excess_table_privileges,
               NOT EXISTS (
                   SELECT 1
                     FROM unnest(%s::text[]) AS control(table_name)
                    WHERE has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'INSERT'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'UPDATE'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'DELETE'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'TRUNCATE'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'TRIGGER'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'REFERENCES'
                          )
                       OR has_any_column_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'INSERT'
                          )
                       OR has_any_column_privilege(
                              current_user,
                              format('public.%I', control.table_name),
                              'UPDATE'
                          )
               ) AS authorization_tables_are_read_only,
               has_schema_privilege(current_user, 'public', 'CREATE') AS can_create_schema_objects,
               EXISTS (
                   SELECT 1
                     FROM pg_catalog.pg_roles AS inherited
                    WHERE inherited.rolname <> current_user
                      AND (
                          inherited.rolsuper OR inherited.rolbypassrls
                          OR inherited.rolcreaterole OR inherited.rolcreatedb
                          OR inherited.rolname IN (
                              'pg_read_all_data', 'pg_write_all_data',
                              'pg_execute_server_program'
                          )
                      )
                      AND pg_has_role(current_user, inherited.oid, 'MEMBER')
               ) AS member_of_privileged_role,
               role.rolreplication AS can_replicate,
               has_function_privilege(
                   current_user,
                   'public.celestin_request_scope_matches(uuid, uuid)'::regprocedure,
                   'EXECUTE'
               ) AS can_evaluate_request_scope,
               has_schema_privilege(current_user, 'public', 'USAGE') AS can_use_public_schema,
               NOT EXISTS (
                   SELECT 1
                     FROM unnest(%s::text[]) AS authorization(table_name)
                    WHERE NOT has_table_privilege(
                                  current_user,
                                  format('public.%I', authorization.table_name),
                                  'SELECT'
                              )
               ) AS can_read_authorization_state,
               (
                   has_table_privilege(current_user, 'public.chat_messages', 'SELECT')
                   AND has_table_privilege(current_user, 'public.chat_messages', 'INSERT')
                   AND NOT has_table_privilege(current_user, 'public.chat_messages', 'UPDATE')
                   AND NOT has_any_column_privilege(
                       current_user, 'public.chat_messages', 'UPDATE'
                   )
                   AND has_table_privilege(current_user, 'public.project_memory', 'SELECT')
                   AND has_table_privilege(current_user, 'public.project_memory', 'INSERT')
                   AND has_table_privilege(current_user, 'public.project_memory', 'UPDATE')
               ) AS can_run_current_memory_tools,
               (
                   has_sequence_privilege(
                       current_user,
                       pg_get_serial_sequence('public.chat_messages', 'id'),
                       'USAGE'
                   )
                   AND has_sequence_privilege(
                       current_user,
                       pg_get_serial_sequence('public.project_memory', 'id'),
                       'USAGE'
                   )
               ) AS can_allocate_memory_ids,
               NOT EXISTS (
                   SELECT 1
                     FROM unnest(%s::text[]) AS unexposed(table_name)
                    WHERE has_table_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'SELECT'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'INSERT'
                          )
                       OR has_table_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'UPDATE'
                          )
                       OR has_any_column_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'SELECT'
                          )
                       OR has_any_column_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'INSERT'
                          )
                       OR has_any_column_privilege(
                              current_user,
                              format('public.%I', unexposed.table_name),
                              'UPDATE'
                          )
               ) AS no_unexposed_tenant_table_privileges
          FROM pg_catalog.pg_roles AS role
         WHERE role.rolname = current_user
    """
    with pool.connection(timeout=timeout) as connection:
        protected = list(PROTECTED_TABLES)
        owned = protected + list(AUTHORIZATION_TABLES)
        cursor = connection.execute(
            query,
            (
                owned,
                protected,
                protected,
                protected,
                protected,
                protected,
                protected,
                list(AUTHORIZATION_TABLES),
                list(AUTHORIZATION_TABLES),
                list(PROTECTED_TABLES[2:]),
            ),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    if (
        row is None
        or any(bool(value) for value in row[:5])
        or not bool(row[5])
        or not bool(row[6])
        or not bool(row[7])
        or not bool(row[8])
        or bool(row[9])
        or bool(row[10])
        or bool(row[11])
        or not bool(row[12])
        or not bool(row[13])
        or not bool(row[14])
        or not bool(row[15])
        or not bool(row[16])
        or not bool(row[17])
    ):
        raise RuntimeError("PostgreSQL runtime role violates the least-privilege/RLS requirements")


def main() -> None:
    """Start the separate hosted runtime with required TLS and explicit config."""
    settings = HostedRuntimeSettings.from_environment()
    app = create_hosted_mcp_app(settings)
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional hosted extra
        raise RuntimeError("Hosted HTTP runtime requires the hosted optional dependencies.") from exc
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.port,
        ssl_certfile=str(settings.tls_certfile),
        ssl_keyfile=str(settings.tls_keyfile),
        proxy_headers=False,
        server_header=False,
        date_header=False,
        limit_concurrency=64,
        timeout_keep_alive=5,
    )
