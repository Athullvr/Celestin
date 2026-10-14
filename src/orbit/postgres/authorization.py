"""Request-scoped PostgreSQL authorization for the hosted scope resolver.

This module is inert at import time. Constructing a factory stores only an
injected connection factory; it does not connect or run migrations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol
from uuid import UUID

from orbit.mcp_server.hosted_scope import (
    HostedAccessDenied,
    HostedAuthorizationSession,
    HostedAuthorizationUnavailable,
    ProjectAction,
    HostedScopeResolver,
    HostedSourceMessageNotFound,
    ProjectAccessRecord,
    ProjectScopedSourceMessage,
    ResolvedProjectScope,
    VerifiedPrincipal,
)


class _Connection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...

    def transaction(self) -> Any: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], _Connection]


class PostgresHostedAuthorizationSession(HostedAuthorizationSession):
    """Authorization reads that lock the authoritative rows until transaction end.

    Lock order is workspace, identity, project, membership, grant, then source
    message. Mutations that revoke access should use the same leading order.
    Existing identity/grant/lifecycle rows are held with FOR SHARE, so an update
    or delete that revokes access waits for this operation's transaction. This
    gives a defined transaction ordering, not instantaneous revocation.
    """

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self._identities: dict[tuple[VerifiedPrincipal, UUID], tuple[UUID, str]] = {}

    @property
    def connection(self) -> _Connection:
        """Connection for trusted storage adapters inside this same transaction."""
        return self._connection

    def is_principal_active(
        self, principal: VerifiedPrincipal, workspace_id: UUID
    ) -> bool:
        """Map trusted issuer/subject/kind to an active internal identity."""
        try:
            workspace = self._connection.execute(
                """SELECT id FROM celestin_workspaces
                     WHERE id = %s FOR SHARE""",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                return False

            if principal.kind == "human":
                row = self._connection.execute(
                    """SELECT id, status FROM celestin_users
                         WHERE issuer = %s AND subject = %s FOR SHARE""",
                    (principal.issuer, principal.subject),
                ).fetchone()
                active_status = "active"
            else:
                row = self._connection.execute(
                    """SELECT id, status FROM celestin_service_identities
                         WHERE workspace_id = %s AND issuer = %s AND subject = %s
                         FOR SHARE""",
                    (workspace_id, principal.issuer, principal.subject),
                ).fetchone()
                active_status = "active"

            if row is None:
                return False
            identity_id, status = row
            if not isinstance(identity_id, UUID):
                identity_id = UUID(str(identity_id))
            self._identities[(principal, workspace_id)] = (identity_id, str(status))
            return status == active_status
        except Exception:
            raise HostedAuthorizationUnavailable(
                "authorization state is unavailable"
            ) from None

    def load_project_access(
        self,
        principal: VerifiedPrincipal,
        workspace_id: UUID,
        project_key: str,
    ) -> ProjectAccessRecord | None:
        """Load lifecycle and explicit grant facts, scoped to one workspace."""
        try:
            identity = self._identities.get((principal, workspace_id))
            if identity is None:
                if not self.is_principal_active(principal, workspace_id):
                    return None
                identity = self._identities[(principal, workspace_id)]
            principal_id, identity_status = identity

            workspace = self._connection.execute(
                """SELECT archived_at FROM celestin_workspaces
                     WHERE id = %s FOR SHARE""",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                return None
            project = self._connection.execute(
                """SELECT id, legacy_project_key, archived_at
                     FROM celestin_projects
                    WHERE workspace_id = %s AND legacy_project_key = %s
                    FOR SHARE""",
                (workspace_id, project_key),
            ).fetchone()
            if project is None:
                return None
            project_id, stored_key, project_archived_at = project
            if not isinstance(project_id, UUID):
                project_id = UUID(str(project_id))

            membership_status: str | None = None
            service_status: str | None = None
            if principal.kind == "human":
                service_status = None
                membership = self._connection.execute(
                    """SELECT status FROM celestin_workspace_memberships
                         WHERE workspace_id = %s AND user_id = %s FOR SHARE""",
                    (workspace_id, principal_id),
                ).fetchone()
                if membership is not None:
                    membership_status = str(membership[0])
                grant = self._connection.execute(
                    """SELECT can_read, can_write, revoked_at
                         FROM celestin_project_memberships
                        WHERE workspace_id = %s AND project_id = %s AND user_id = %s
                        FOR SHARE""",
                    (workspace_id, project_id, principal_id),
                ).fetchone()
            else:
                service_status = identity_status
                membership = None
                grant = self._connection.execute(
                    """SELECT can_read, can_write, revoked_at
                         FROM celestin_service_project_grants
                        WHERE workspace_id = %s AND project_id = %s
                          AND service_identity_id = %s
                        FOR SHARE""",
                    (workspace_id, project_id, principal_id),
                ).fetchone()

            return ProjectAccessRecord(
                principal_id=principal_id,
                workspace_id=workspace_id,
                project_id=project_id,
                project_key=str(stored_key),
                workspace_archived=workspace[0] is not None,
                project_archived=project_archived_at is not None,
                membership_status=membership_status,
                service_status=service_status,
                grant_present=grant is not None,
                grant_revoked=grant is not None and grant[2] is not None,
                can_read=grant is not None and bool(grant[0]),
                can_write=grant is not None and bool(grant[1]),
            )
        except HostedAuthorizationUnavailable:
            raise
        except Exception:
            raise HostedAuthorizationUnavailable(
                "authorization state is unavailable"
            ) from None

    def load_source_message_reference(
        self, scope: ResolvedProjectScope, message_id: str
    ) -> ProjectScopedSourceMessage | None:
        """Resolve a decimal public message ID only inside the resolved scope."""
        if not isinstance(message_id, str) or not message_id.isdecimal():
            return None
        try:
            numeric_id = int(message_id)
            if numeric_id < 1 or str(numeric_id) != message_id:
                return None
            row = self._connection.execute(
                """SELECT id FROM chat_messages
                    WHERE workspace_id = %s AND project_id = %s AND id = %s
                    FOR KEY SHARE""",
                (scope.workspace_id, scope.project_id, numeric_id),
            ).fetchone()
            if row is None:
                return None
            return ProjectScopedSourceMessage(
                message_id=str(row[0]),
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
            )
        except Exception:
            raise HostedAuthorizationUnavailable(
                "authorization state is unavailable"
            ) from None


class PostgresHostedAuthorizationSessionFactory:
    """Open one connection/transaction per authorized hosted operation."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresHostedAuthorizationSessionFactory:
        """Create a lazy optional-psycopg factory; no import or connection now."""
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn must be a non-empty string")

        def connect() -> _Connection:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Hosted PostgreSQL authorization requires the psycopg extra"
                ) from exc
            return psycopg.connect(dsn)

        return cls(connect)

    @contextmanager
    def transaction(self) -> Iterator[PostgresHostedAuthorizationSession]:
        """Yield one session; commit on normal exit, rollback on error, always close."""
        try:
            connection = self._connection_factory()
        except Exception:
            raise HostedAuthorizationUnavailable(
                "authorization service is unavailable"
            ) from None
        try:
            with connection.transaction():
                yield PostgresHostedAuthorizationSession(connection)
        except (HostedAccessDenied, HostedSourceMessageNotFound, HostedAuthorizationUnavailable):
            raise
        except Exception:
            # This also covers commit failures. Do not expose SQL, DSNs, or driver details.
            raise HostedAuthorizationUnavailable(
                "authorized operation could not be completed"
            ) from None
        finally:
            try:
                connection.close()
            except Exception:
                # Do not claim success if the request resource could not close.
                raise HostedAuthorizationUnavailable(
                    "authorization service could not release its database session"
                ) from None

    def execute_authorized(
        self,
        resolver: HostedScopeResolver,
        principal: VerifiedPrincipal,
        project_key: str,
        action: ProjectAction,
        operation: Callable[[PostgresHostedAuthorizationSession, ResolvedProjectScope], Any],
        *,
        source_message_id: str | None = None,
    ) -> Any:
        """Return only after the authorized operation's transaction commits."""
        with self.transaction() as session:
            result = resolver.execute(
                session,
                principal,
                project_key,
                action,
                operation,
                source_message_id=source_message_id,
            )
        return result
