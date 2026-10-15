# Hosted identity and project scope boundary

## Status

The types and resolver in `orbit.mcp_server.hosted_scope` remain an application
foundation and are not connected to the MCP server. The injectable
`orbit.postgres.authorization.PostgresHostedAuthorizationSessionFactory` now
provides a request-scoped database implementation for hosted authorization.
It does not authenticate tokens, select a backend, or change local stdio/SQLite
behavior. Its SQL is covered by scripted unit tests, not a live PostgreSQL run.

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
- Storage/retrieval must use the resolved UUID scope for every query, including
  source-message lookups, search candidates, caches, and context assembly.

The resolver exposes `execute(session, principal, project_key, action, operation)`
to make the order explicit: it resolves permission first, then invokes the
operation with the same request session and immutable scope. The PostgreSQL
factory's `execute_authorized` wraps that call in one connection transaction,
commits before returning its result, rolls back on failure, and closes the
connection. Factory construction and module import do not connect or migrate.

The PostgreSQL session locks rows in this order: workspace, identity, project,
membership, grant, then source message. Existing authorization/lifecycle rows
are selected `FOR SHARE` and remain locked through the protected operation.
Updates that suspend/revoke/retire those rows therefore serialize behind an
already-authorized operation; if revocation commits first, a later request
observes it and is denied. Administrative mutations should follow the same
leading lock order to reduce deadlocks. These are transaction-ordering
semantics, not instantaneous revocation or a test of PostgreSQL's live lock
implementation.

For source provenance, a write that references a message must call
`execute(..., source_message_id=...)`. After authorization, the session's
`load_source_message_reference(scope, message_id)` must look up the ID with both
`scope.workspace_id` and `scope.project_id` in its predicate. The resolver
rechecks the returned workspace/project metadata and reports missing and
out-of-scope references as the same not-found condition before invoking the
write operation. The PostgreSQL authorization session performs this lookup in
the same request transaction and retains the database composite foreign key as
the final relational-integrity guard. Hosted MCP/data adapters are still not
wired to this session.

## Storage integration seam

`MemoryStore` and `RetrievalData` currently accept public project strings for
the local SQLite path. A future hosted implementation must accept
`ResolvedProjectScope` (or a narrower typed projection derived from it), use
its workspace/project UUIDs for every query, and never infer permission from
the string key. Persistence writes must validate source-message references
within that scope; retrieval candidate search, authoritative reloads, and
context assembly must use the same scope. This task does not change either port
or select a hosted adapter, so the resolver is not yet an enforcement point for
actual MCP requests.

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
session. `tests/postgres/test_hosted_authorization.py` uses a scripted connection
to check identity mapping, SQL scoping/locks, denials, source references,
transaction lifecycle, and redacted errors. These are unit/contract tests, not
PostgreSQL execution, authentication-provider, transport, pooling, or
concurrent-revocation tests. Those tests are required before hosted mode can be
enabled.

The next integration seam is a reviewed trusted transport authenticator and
hosted persistence/retrieval adapters that accept `ResolvedProjectScope`. This
resolver/session is not connected to server tools. Existing stdio MCP tools and
SQLite adapters remain unchanged until a separate reviewed integration task.
