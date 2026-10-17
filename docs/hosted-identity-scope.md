# Hosted identity and project scope boundary

## Status

The types and resolver in `orbit.mcp_server.hosted_scope` remain an application
foundation and are not connected to the MCP server. The injectable
`orbit.postgres.authorization.PostgresHostedAuthorizationSessionFactory` now
provides a request-scoped database implementation for hosted authorization.
`execute_authorized_request` now creates a `PostgresRequestUnitOfWork` after the
resolver grants access. Its memory store, retrieval data adapter, and shared
retrieval service borrow the authorization session's connection and leave
transaction finalization to the session factory. This does not authenticate
tokens, select a backend, connect the flow to MCP, or change local stdio/SQLite
behavior. Its SQL is covered by scripted unit tests, not a live PostgreSQL run.

`orbit.mcp_server.hosted_identity` defines the supported hosted application
entry point: `HostedRequestBoundary.execute_authorized_request`. It orchestrates
an injected `PrincipalAuthenticator` and delegates to the factory's internal
request executor only after authentication returns a `VerifiedPrincipal`. The
boundary requires an explicitly injected workspace binding, principal-status
provider, and request executor. No concrete authenticator or workspace-binding
provider exists, and the boundary is not used by MCP handlers. The protocol and
the freely constructible `VerifiedPrincipal` value do not prove credential
authenticity; a future transport adapter/provider must validate credentials
before returning a principal. Missing dependencies and authentication failures
do not open a database connection or execute the protected callback.

The request executor and its transaction/session entry points are underscored
internal APIs. The request UoW has no public constructor, does not expose its
authorization session or resolved scope as public fields, and creates its
persistence/retrieval adapters only through internal request-bound factories.
The resolver and low-level authorization-session methods are also trusted
application primitives, not handler entry points.
Standalone PostgreSQL adapter constructors remain available for trusted
single-workspace tooling and adapter tests; they do not authorize a human or
service principal and must never be injected into hosted MCP handlers. These
API boundaries prevent accidental composition errors, not hostile Python code
running in the same process. Same-process code is trusted and can deliberately
call underscored methods, construct values, or open its own database connection.
The future hosted application composition must therefore expose only the
boundary to transport handlers and keep the executor, DSN, and standalone
adapters out of handler dependencies.

## Trust and selection

`VerifiedPrincipal` is an internal value that a future trusted authenticator
creates after validating a human or service credential. It contains the trusted
issuer, subject, and principal kind. It must never be constructed from a caller's
MCP arguments. The value itself does not perform authentication.

The `project` string remains a selector, not an access grant. A server-side
`WorkspaceBinding` supplies the active workspace associated with the verified
credential/connection. The resolver asks its request-scoped authorization session
to resolve the exact public project key within that workspace. It does not search
other workspaces, so identical keys in different workspaces cannot select one
another. No workspace selector is added to the public MCP contract.

## Authorization rules

- The principal status provider must confirm the authenticated identity is
  active. An inactive identity is denied before workspace or project lookup.
- Human principals need an active membership in the selected workspace and an
  explicit, unrevoked project grant.
- Service principals need an active service identity and an explicit,
  unrevoked service-project grant. The current schema models these separately
  from human workspace memberships.
- Both principal kinds require an unarchived workspace and project. Workspace
  owner/admin roles do not imply access to project data.
- Read requires `can_read`; write requires `can_write` and `can_read`.
- Missing identity, workspace binding, project, membership, or grant denies
  access. Infrastructure errors return a generic unavailable failure. Neither
  failure message includes another workspace's project existence or database
  details.
- Request-bound storage/retrieval use the resolved UUID scope for every query,
  including source-message lookups, search candidates, authoritative reloads,
  and context assembly. The request-bound memory store requires write
  permission; retrieval requires read permission. A mismatched public project
  key is denied before adapter SQL.

The resolver exposes `execute(session, principal, project_key, action, operation)`
to make the order explicit: it resolves permission first, then invokes the
operation with the same request session and immutable scope. The PostgreSQL
factory's `execute_authorized` wraps that call in one connection transaction.
Its `execute_authorized_request` additionally binds the `PostgresMemoryStore`
and `PostgresRetrievalData` to that session's connection and resolver-issued
scope, then exposes a `RetrievalService` over that data adapter. The factory
commits before returning a successful result, rolls back on failure, and closes
the connection; bound adapters do none of those operations and cannot acquire
a replacement connection. Factory construction and module import do not
connect or migrate.

The PostgreSQL session locks rows in this order: workspace, identity, project,
membership, grant, then source message. Existing authorization/lifecycle rows
are selected `FOR SHARE` and remain locked through the protected operation.
Updates that suspend/revoke/retire those rows therefore serialize behind an
already-authorized operation; if revocation commits first, a later request
observes it and is denied. Administrative mutations should follow the same
leading lock order to reduce deadlocks. These are transaction-ordering
semantics, not instantaneous revocation or a test of PostgreSQL's live lock
implementation.

For source provenance, a hosted operation that references a message should pass
`source_message_id` to `execute_authorized_request`. After authorization, the
session's `load_source_message_reference(scope, message_id)` must look up the ID
with both `scope.workspace_id` and `scope.project_id` in its predicate. The resolver
rechecks the returned workspace/project metadata and reports missing and
out-of-scope references as the same not-found condition before invoking the
write operation. The PostgreSQL authorization session performs this lookup in
the same request transaction and retains the database composite foreign key as
the final relational-integrity guard. Request-bound adapters are composed in
that transaction, but hosted MCP/data adapters are still not wired to tools.

## Storage integration seam

`MemoryStore` and `RetrievalData` retain their existing public project-string
contracts for local SQLite. Internal PostgreSQL `_for_request(connection,
scope)` factories accept only a `ResolvedProjectScope`; project strings are
checked against that scope and do not select the tenant. Persistence source
checks and retrieval candidate and authoritative reads use the scope's
workspace/project UUIDs. The request UoW creates these adapters itself and
cannot be supplied standalone adapter instances through its supported
constructor. Standalone `from_dsn` adapters retain their explicit fixed-scope
behavior and are not hosted authorization paths. No hosted adapter is selected
in MCP, so the resolver is still not an enforcement point for actual MCP
requests.

## Schema gap and follow-up

The immutable migration baseline's `celestin_users` table has no
active/suspended status. Additive migration `0002_user_status.sql` adds
`status TEXT NOT NULL DEFAULT 'suspended'` with an `active|suspended` check;
backfilled and default-created users remain denied until trusted administration
explicitly activates them. The PostgreSQL session maps human principals by the
baseline's globally unique `(issuer, subject)` and service principals by
`(workspace_id, issuer, subject)`. Principal `kind` selects the identity table.
Service identity scope is intentionally workspace-local. Provider issuer and
subject stability, and whether upstream account disablement must also be
checked, remain decisions for a future authenticator; no identity provider is
integrated.

The schema also permits suspended members and revoked service identities to
retain grant rows, and it does not enforce a last-active-workspace-owner rule.
The hosted resolver checks retained suspension/revocation state. Owner lifecycle
remains a separate transactional workspace-administration task.

## Tests and limits

`tests/test_hosted_scope.py` uses synthetic principals and a fake authorization
session. Offline authentication-boundary tests in
`tests/postgres/test_hosted_identity_boundary.py` verify unavailable and
rejected authentication paths, exception redaction, and that raw caller claims
are not passed as principals. Request-UoW tests enter through the boundary and
use scripted connections to check that missing authentication cannot connect,
standalone adapters are not selected, and the handler-facing UoW does not
expose public session/scope fields. Scripted tests in
`tests/postgres/test_hosted_authorization.py`,
`tests/postgres/test_request_unit_of_work.py`,
`tests/storage/test_postgres_memory_store.py`, and
`tests/retrieval/test_postgres_data.py` cover SQL scoping, adapter sharing, and
ownership of the request transaction. They do not prove PostgreSQL execution,
authentication-provider, transport, pooling, or live concurrent-revocation
behavior. Those tests are required before hosted mode can be enabled.

The remaining integration seam is a concrete, reviewed transport authenticator
and trusted workspace-binding source, followed by a hosted MCP composition that
invokes the boundary with transport evidence rather than tool arguments. This
resolver/session/UoW is not connected to server tools. Existing stdio MCP tools
and SQLite adapters remain unchanged until a separate reviewed integration
task.
