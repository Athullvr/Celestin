# Hosted Authorization and Revocation Protocol

**Status: source-backed design proposal; not an accepted security design.** This document records current checked-in behavior and proposes a transaction protocol for review. It does not authorize migration 0010, hosted multi-tenant service, or a database operation. No PostgreSQL/Neon catalog was inspected for this task.

The current branch and reviewed source baseline were `codex/celestin-core-memory-platform` at `2f3985d6b17e5f4983cb45dfeea786d432146704`. Existing local changes were preserved. The offline evaluator described below consumes supplied data and is not a live evidence collector.

## Status vocabulary

- **IMPLEMENTED (source-level):** visible in current Python or migration source. It is not a claim that deployed PostgreSQL has the same state.
- **PROPOSED — NOT APPROVED:** a candidate protocol or control requiring product/security/storage review.
- **UNVERIFIED:** needs a live, explicitly approved disposable PostgreSQL target or authoritative provider evidence.
- **BLOCKED:** do not enable hosted tenant service until the listed decision and evidence exist.

## 1. Current trusted-identity model

### What the application currently establishes

| Identity or value | Current source behavior | What it proves and does not prove |
|---|---|---|
| Hosted bearer credential | `Auth0TokenVerifier._verify_sync` validates the configured JWT profile, signature/key, issuer, audience, time claims, allowlisted client, and scopes; `Auth0AccessTokenAuthenticator.authenticate` accepts only an `AccessToken` carrying the verifier's in-process marker. `create_hosted_mcp_server` composes these with `HostedRequestBoundary`. | The hosted composition can create a principal from its verifier-issued transport object. It does not protect against arbitrary malicious Python code in the same process. No Auth0 tenant or live token was checked here. (`src/orbit/mcp_server/hosted_auth.py`; `src/orbit/mcp_server/hosted_identity.py::HostedRequestBoundary`; `src/orbit/mcp_server/hosted_server.py::create_hosted_mcp_server`.) |
| `VerifiedPrincipal` | Contains `(issuer, subject, kind)`; humans are queried by issuer/subject and service identities by workspace/issuer/subject. | Application identity input for the resolver. A constructor or type check alone is not a boundary against hostile same-process code. (`src/orbit/mcp_server/hosted_scope.py::VerifiedPrincipal`; `src/orbit/postgres/authorization.py::PostgresHostedAuthorizationSession.is_principal_active`.) |
| Workspace selector | `ExplicitWorkspaceBinding.workspace_for` returns the explicit request selector as a candidate. `HostedScopeResolver.resolve` then loads authoritative state and denies inactive, missing, archived, ungranted, revoked, or insufficiently permitted access. | The request value selects a candidate workspace; it is not proof of membership or permission. (`src/orbit/mcp_server/hosted_server.py::ExplicitWorkspaceBinding`; `src/orbit/mcp_server/hosted_scope.py::HostedScopeResolver.resolve`.) |
| Resolved project scope | Issued by the resolver after identity, workspace/project lifecycle, membership/service status, explicit grant, and action checks. `HostedDatabasePools.project_connection` selects only the exact configured `(workspace_id, project_id)` pair. | Application authorization and route selection. The project connection must still repeat authorization; the route result is not authority to run a handler. (`src/orbit/mcp_server/hosted_scope.py::ResolvedProjectScope`; `src/orbit/mcp_server/hosted_server.py::HostedDatabasePools.project_connection`.) |
| PostgreSQL project login | Migration 0008 stores a protected mapping from `login_role_name` (`session_user`) to one workspace/project; RLS helper functions compare rows with that mapping. Migration 0009's project request-lock wrapper checks that the authenticated database session maps to the supplied workspace before taking its workspace lock. | Database identity for a configured connection, not the end-user identity. RLS and mapping behavior is source intent only until live tests establish it. The lock wrapper is workspace-wide, while row access is workspace-and-project scoped. (`src/orbit/postgres/migrations/0008_project_scoped_runtime_roles.sql`; `src/orbit/postgres/migrations/0009_project_request_lock_scope.sql`.) |
| Authorization reader login | Migration 0008 grants a reader group `SELECT` on authorization tables and installs reader policies with `USING (true)`. The request factory uses a control connection to resolve a candidate route before opening the project connection. | A shared, cross-workspace control-plane database identity. PostgreSQL does not see which human/service token the application is resolving. Its scope must not be inferred from a caller-supplied workspace/principal argument. It is not a tenant-content credential. (`src/orbit/postgres/migrations/0008_project_scoped_runtime_roles.sql`; `src/orbit/postgres/authorization.py::ProjectScopedPostgresHostedAuthorizationSessionFactory`.) |
| Authorization-admin login | `PostgresAccessProvisioner` authenticates a supplied token, then checks the actor's active user and owner/admin workspace membership in the same admin transaction before changing grants. Migration 0008 grants the admin group broad authorization-table and protected mapping operations. | The code path checks the human actor at the application layer. The shared database login is not bound to that human. A holder of the raw admin database credential can issue SQL outside the provisioner checks and is therefore a high-trust control-plane principal. (`src/orbit/postgres/provisioning.py::PostgresAccessProvisioner`; `src/orbit/postgres/migrations/0008_project_scoped_runtime_roles.sql`.) |
| Provisioning operator | The provisioner API accepts an Auth0-verified human and requires an active owner/admin membership for the selected workspace. `ProjectDatabaseLoginRegistry` is a lower-level connection-injected component for registering pre-created logins. There is no composed operator CLI/preflight that authenticates a human, verifies all role/ACL invariants, and then provisions them. | Current provisioning helpers, not a complete operator workflow. The identity that invokes the low-level registry is not independently represented in PostgreSQL by that API. (`src/orbit/postgres/provisioning.py::PostgresAccessProvisioner._verified_admin`, `_require_workspace_admin`, `ProjectDatabaseLoginRegistry`.) |
| Migration executor | `celestin-migrate` reads an explicitly named DSN environment variable and calls `apply_migrations`; the runner holds a session advisory lock on its migration connection and applies each migration and ledger entry in a transaction. | Possession of the operator credential and invocation of the explicit command. It is separate from normal server startup, but the source does not establish who operated it or the actual database role. (`src/orbit/postgres/migrate_cli.py::main`; `src/orbit/postgres/migrations/runner.py::apply_migrations`.) |
| Lock-function owner / provider administrator | Migrations do not explicitly establish a separate non-login owner for the functions; ownership depends on the role that executes DDL. Readiness has owner/security expectations. Provider-controlled capabilities are not represented by source. | The actual owner, grants, and provider rights are unknown until a live catalog and authoritative provider evidence are reviewed. |

The normal hosted path is composed in source, but hosted startup rejects configuration unless project-role isolation is explicitly enabled; the fail-closed setting defaults to disabled. Its readiness validators also reject currently unverified lock-scope signatures. This design document does not change that gate. Local stdio/SQLite is a separate composition and remains unaffected.

### Current request path

```mermaid
sequenceDiagram
    participant C as Hosted MCP client
    participant A as Auth0 verifier / request boundary
    participant R as Authorization-reader transaction
    participant P as Configured project-login transaction
    participant H as Handler and request UoW
    C->>A: Bearer token + explicit workspace/project selectors
    A->>A: Verify access token; enforce API scope
    A->>R: Resolve candidate route and access
    Note over R: Current source acquires reader wrapper locks using workspace/principal arguments
    R-->>A: Resolved scope (routing result only)
    A->>P: Select exact configured workspace/project pool
    P->>P: Verify session_user scope; repeat authorization and bind scope
    P->>H: Invoke only after final resolver authorization
    H->>P: Scoped persistence/retrieval on the same transaction connection
    H-->>P: Result or error
    P-->>A: Commit on success; rollback on error; release connection
    A-->>C: Result or sanitized denial/error
```

The first control transaction is closed before the project transaction begins. The project transaction repeats the authorization checks, so a revocation between route selection and project-pool work must be caught there. `PostgresRequestUnitOfWork` binds evidence, memory, and retrieval adapters to that project session; it does not own commit/rollback. (See `src/orbit/postgres/authorization.py::ProjectScopedPostgresHostedAuthorizationSessionFactory._execute_authorized_request`, `PostgresHostedAuthorizationSessionFactory._transaction`, and `src/orbit/postgres/unit_of_work.py::PostgresRequestUnitOfWork._bind`.)

## 2. Scope-mapping and coordination options

No option is accepted by this document. The database identity facts above do not support treating `workspace_id`, `project_id`, principal labels, GUCs, or arbitrary lock keys supplied by a caller as trusted authorization evidence.

| Design | Trust and role boundary | Isolation and concurrency | Revocation behavior | Availability, recovery, cost, and proof required |
|---|---|---|---|---|
| **A. Database-verified identity-to-scope mapping** | Bind each content-capable project login to one protected scope via `session_user`; keep RLS as the row boundary. If reader/admin lock scope must be tenant-specific, use identities mapped to that scope or leave their tenant lock API unavailable. The shared reader/admin database logins do not identify end users. | A compromised project login cannot select another mapping if mapping/RLS/role attributes are actually enforced. Current project lock is at workspace level, so projects in one workspace contend together. Mapping does not contain a compromised app process holding several project credentials. | Request and revoker must use the same verified scope coordination and final authorization reads must be fresh after any wait. | Lowest conceptual change for existing project pools if ACL/ownership support is verified. Public built-in advisory execution remains an availability path until denied; lock duration, pool exhaustion, role rotation, and recovery need live tests. Per-scope control-plane credentials increase provisioning and rotation work. |
| **B. Database-mediated operations with no arbitrary lock key API** | Functions derive scope only from database-authenticated identity/mapping or from rows whose authorization is checked within the database operation. A `SECURITY DEFINER` wrapper that accepts arbitrary caller-selected keys or merely hashes caller-supplied IDs is not trusted scope validation. | Can constrain what a role can contend on, but does not create human identity for a shared reader/admin login. Any privileged procedure must have a narrow caller model, owner, fixed safe path, qualified references, argument validation, and exact execute grants. | A single transaction can serialize validation and change only if all relevant request and writer paths use the same protocol and recheck state before protected work. | Lower application-level lock misuse, but high function-owner/ACL review burden. Test arbitrary-target attempts, direct calls, RLS interactions, owner privileges, rollback, and concurrent use on live PostgreSQL. Provider ownership/ACL support is unresolved. |
| **C. Transactional row-lock coordination** | Lock the authoritative identity, scope mapping, lifecycle, membership, and grant rows under the project login's actual session identity, then re-read/authorize before work. Writers must lock the same facts before mutation. | Removes advisory-key choice from ordinary request/revocation coordination only if every relevant query, insert/update/delete, trigger, identity transition, and provisioning path is converted. RLS-visible row locking and required SQL privileges are unverified. Absent rows require a stable parent/anchor lock to prevent insertion races. | Request-first means revocation waits to commit; revocation-first means a later request waits and must observe or fail on the changed state. A globally consistent row order is needed to avoid deadlocks. | Avoids dependence on advisory ACL changes for those paths, but is a substantial redesign. Current request authorization uses plain SELECTs; migrations 0008–0009 still have advisory triggers/wrappers; the migration runner also uses advisory locking. Requires live tests for row-lock permission, phantoms/absent rows, deadlocks, rollback, cancellation, and a separate migration coordinator. |
| **D. Tenant-separated databases** | Per-project databases provide a narrower DB blast radius than per-workspace databases; each still needs application authentication/authorization and least-privileged roles. | Advisory locks are database-local, but per-workspace databases retain within-workspace contention. A central process holding multiple DSNs can still cross database boundaries. | Central identity/membership revocation across tenant databases is not one atomic transaction. Fan-out/outbox, partial failure, and reconciliation semantics are needed. | More databases, roles, pools, secrets, migrations, backups, monitoring, and cost. Does not solve app-process compromise or remove the need for authorization. Test credential separation, partial provisioning/revocation, and migration consistency. Provider limits/cost are unknown. |

### Decision posture

**PROPOSED — NOT APPROVED:** preserve the project `session_user` mapping and forced-RLS content boundary. For any advisory design, limit project lock scope from that mapping, remove arbitrary reader routing locks, keep global admin mutations outside request dispatch, and separate the migration-runner session-lock profile from any function-owner transaction-lock profile. This is a candidate because it fits the current project-pool structure; it is not ready to implement against the selected provider while role ACL/ownership facts and transaction isolation remain unverified.

The repository does not justify an unconditional choice between scope-mapped advisory coordination and a complete row-lock redesign. Database separation is a product/operations choice. **Until product/security, storage, and provider decisions are recorded and acceptance evidence exists, hosted multi-tenant serving remains disabled; local SQLite/stdio remains the safe path.**

## 3. Revocation semantics and transaction ordering

`docs/hosted-identity-scope.md` and `docs/postgres-integration-tests.md` document an intended policy: a request that already holds the matching authorization boundary may finish; revocation waits and commits later; a request starting after the revocation commit is denied. The repository's decision register calls this a documented behavior but says a formal owner decision was not located. Treat it as **documented intent, not separate product approval**.

### Conditional protocol proposal — wait for in-flight protected work

The following sequence is a **proposal**, not a guarantee established by source tests or live PostgreSQL. It assumes a selected coordinator, every relevant mutation path participating, and an explicit transaction-isolation policy.

**Request:**

1. The HTTP authentication boundary validates the access token and required API scope. The workspace/project selectors remain untrusted resource selectors.
2. A short control transaction resolves a candidate project route. **PROPOSED:** make this routing-only and remove its global reader lock; it must not authorize a protected handler or read tenant content.
3. Acquire the server-configured project login for exactly the resolved `(workspace_id, project_id)`; never select a pool from an untrusted key alone and never fall back to a shared content credential.
4. Begin the protected transaction. Apply approved bounded timeouts and an explicitly selected isolation contract.
5. Acquire the scope-bound request coordination primitive before authorization reads. For the existing advisory candidate, verify `session_user` against the protected mapping and acquire the mapped workspace shared transaction lock. For a row-lock candidate, lock every relevant authorization fact row (including required parent rows) in the approved order.
6. Re-read principal status, workspace/project lifecycle, membership/service grant, project permission, and scope mapping after the coordination wait. Bind `ResolvedProjectScope` only after all checks pass. A stale routing result alone never authorizes the request.
7. Invoke the handler and all request persistence/retrieval through the same transaction connection. Hold the coordination primitive through the transaction's commit or rollback.
8. Commit only on success. On denial/error/cancellation, roll back, close/reset the connection lease, and release transaction-scoped locks. Do not automatically retry a protected write whose commit outcome is uncertain; delivery replay remains a separate D-08 contract.

**Concurrent revocation:**

1. Authenticate the administrative access token in the trusted application boundary. Start a distinct authorization-admin transaction; do not place the admin DSN in ordinary tool-handler code.
2. Acquire exclusive coordination for the exact affected authorization scope, in the same globally defined order used by every writer. Re-check the actor's active principal and owner/admin permission, workspace/project lifecycle, and target identity/grant under that transaction; lock target rows as required.
3. Update status, membership/grant, lifecycle, or login mapping and its audit record atomically. Commit.
4. The revocation **linearization point is the successful transaction commit**, but only if all requests and writers participated in the same proven coordination protocol. If a request acquired the conflicting shared lock first, the revoker waits and cannot commit until that request ends. The in-flight request is not cancelled. If the revoker acquired its exclusive boundary first, a waiting request must re-read committed state and deny before the handler.
5. If the isolation mode can reuse a pre-wait snapshot, the implementation must either pin a mode whose later authorization statement sees the committed state, use a locking/read protocol that detects the race, or abort and restart the entire authorization transaction from its beginning. It must never continue on a possibly stale authorization snapshot.

### Isolation, timeout, and failure gates

Current Python opens `connection.transaction()` and sets transaction-local `statement_timeout`; it does not explicitly set transaction isolation, `lock_timeout`, a whole-request deadline, or `idle_in_transaction_session_timeout` (`src/orbit/postgres/authorization.py::PostgresHostedAuthorizationSessionFactory._transaction`; `src/orbit/mcp_server/hosted_server.py::HostedRuntimeSettings`). A server's default isolation is not a checked-in guarantee. Therefore “revoker first, waiter sees revocation” is not proven by call order alone. **PROPOSED:** either explicitly require and test `READ COMMITTED` for the protected request transaction, so the post-wait authorization queries take fresh command snapshots, or choose a row-lock/serialization protocol that aborts stale snapshots and forces a fresh authorization transaction. The owner must approve the selected rule; live behavior must be tested.

- Pool and connection timeouts bound acquisition/connection setup, not time spent in a handler transaction.
- A per-statement timeout does not bound CPU/network time in application code between statements. Set an application transaction deadline and database lock/idle limits from an approved SLO.
- Timeout/cancellation before commit must roll back and release resources. A connection loss during commit can leave the caller uncertain whether a revocation/write committed; inspect authoritative state in a fresh authorized operation rather than assuming rollback.
- A request starting after revocation commit must use a fresh protected transaction and deny if principal status, membership, grant, lifecycle, or login mapping is revoked.
- Immediate revocation/cancellation of an already-running handler is a different policy and is **not** provided by transaction locks. If required, it needs an explicit request registry/cancellation/fencing design and separate race tests.

## 4. Advisory-lock operations and privilege boundary

The checked-in code uses a narrow subset of PostgreSQL's overload family:

| Operation | Current source caller | Coordination lifetime | Exact source-level need |
|---|---|---|---|
| `pg_advisory_lock(bigint)` and `pg_advisory_unlock(bigint)` | `src/orbit/postgres/migrations/runner.py::_lock`, `::_unlock` | Session lock held around migration discovery/application; unlock uses the same connection in `finally`. | The current runner's direct session-lock pair. It does not call the two-integer overloads or try-lock variants. |
| `pg_advisory_xact_lock_shared(bigint)` | SQL helpers created in migrations 0008–0009 and called through `src/orbit/postgres/authorization_locking.py` | Shared transaction lock held through authorization and protected request transaction. | Request wrapper primitive. 0008 also uses it for the broader reader wrapper; 0009 adds the project-login scope-checking wrapper. |
| `pg_advisory_xact_lock(bigint)` | 0008 authorization-write helpers and 0008–0009 trigger functions | Exclusive transaction locks held through provisioning/revocation transaction. | Writer/trigger primitive. |

Readiness enumerates 21 overload signatures and validates ACL metadata for the full supported roster (`src/orbit/mcp_server/hosted_server.py::_ADVISORY_LOCK_SIGNATURES`, `_validate_advisory_lock_privilege_catalog`). That is a **catalog-inspection surface**, not evidence that the application calls every overload. The current `migration` allowed profile combines the runner's session pair with the two transaction functions needed by functions owned by that same profile. If migration execution and function ownership are separated, the profiles must be split rather than granting unrelated functions to the runner.

Migrations 0008–0009 revoke PUBLIC from Celestin helper functions, but do not revoke PUBLIC execution on PostgreSQL built-in advisory functions. Their request/admin wrappers are invoker-security in the migration definitions, while runtime readiness expects no direct built-in privileges and stricter function profiles; trigger functions are security-definer with ownership determined by the DDL executor unless separately changed. This is a source mismatch, not a live ACL finding. Actual `PUBLIC`, direct, inherited, grantor, grant-option, ownership, and effective privileges are **UNVERIFIED**.

The reader wrapper takes caller-supplied workspace/principal fields; writer wrappers take caller-supplied workspace/principal fields. Only the project wrapper checks the protected mapping, and it checks the mapped workspace (RLS/scope binding later checks the project). A shared reader/admin role does not prove the human identity or workspace authorization associated with these arguments. Do not make such a wrapper privileged merely by changing it to `SECURITY DEFINER`.

Lock-key hashing has a type-tagged JSON representation, `celestin-auth-v1:` namespace, `hashtextextended`, and seed `0` in checked-in SQL. A hash collision can create false contention; it is not authorization. The migration runner uses a fixed bigint key. Collision separation between that key and hashed application keys is not demonstrated. A credential able to invoke arbitrary advisory built-ins may interfere with locks across the database; this is an **availability/coordination** risk, not by itself a row-read authorization bypass. `REVOKE ... FROM PUBLIC` would have database-wide effects on other workloads and must be reviewed for the selected database.

If the provider cannot support the needed ACL/owner operations, do not claim advisory-lock isolation. Compare a complete row-lock conversion (including all triggers and the migration coordinator), tenant-separated databases, or a different verified host. If no candidate meets the threat model, keep hosted mode disabled.

## 5. Offline readiness API: what it can establish

`src/orbit/mcp_server/hosted_preflight.py::assess_hosted_onboarding` accepts an onboarding request, non-secret configuration metadata, and caller-supplied catalog rows. The evidence shape includes claimed database/schema identity, observation time, per-role login/probe/advisory ACL rows, function/policy/trigger rows, and privileged membership rows. The evaluator validates IDs, exact configured role inventory, freshness, cross-field consistency, and the row content using existing source validators.

It **cannot** establish that the evidence was collected from PostgreSQL, that it came from the claimed database/login, that it is authentic or untampered, that the provider allows a future ACL change, or that any PostgreSQL locking/RLS behavior works. Matching strings for configured and supplied database identity are not attestation. `provider_capability="supported"` is an input assertion, not proof. The serialized report always says `evidence_level=offline_structural_only`, `live_database_verified=false`, `service_permitted=false`, `provisioning_permitted=false`, and `operational_status=BLOCKED`.

The offline runtime assessment examines project-runtime and reader profiles; privileged preflight separately examines admin/migration profiles and configured group membership. Neither is an operator execution path; neither provisions roles or runs migrations. `_assert_safe_hosted_pools` checks only the request reader/project pools and is deliberately separate from privileged checks. Existing `tests/test_hosted_server.py::test_request_pool_readiness_does_not_run_privileged_admin_preflight` protects that separation. Catalog fixtures and the offline assessment are tests of Python validation only.

## 6. Decision and evidence gate

No responsible individual/team beyond role labels is identified by the checked-in documents. These decisions remain open:

1. **Product/security:** choose wait-for-in-flight revocation versus immediate cancellation/fencing; confirm whether the documented wait policy is the desired product policy.
2. **Product/security + storage:** choose a coordination architecture and define which request, grant, identity, lifecycle, login-mapping, provisioning, and revocation paths participate.
3. **Storage/database owner:** select transaction isolation and timeout semantics; specify what a waiter must do if fresh authorization cannot be established.
4. **Database/provider owner:** provide authoritative evidence for exact built-in advisory ACL inspection/revoke/grant, function ownership, role membership, grant option, and whether required changes/recovery are transactionally supported for the selected Neon configuration. No Neon capability is asserted here.
5. **Operations/security:** identify distinct migration, reader, admin, function-owner, and project login identities; define credential source, rotation/revocation, audit trail, and operator separation.
6. **SRE/product:** set lock wait, statement, whole-transaction, idle transaction, and cancellation limits from service objectives.

Before migration 0010 or live enablement: record the selected design and revocation policy; reconcile readiness with the exact DDL owner/security/search-path/grant model; split runner and function-owner privileges if distinct; verify the migration runner's lock recovery; run the live test matrix against an explicitly approved fresh disposable database with separate identities; test both request-first and revocation-first races, isolation mode, direct lock attempts, cross-project RLS, timeout/cancel, pool cleanup, and migration failure/retry. None of those live validations was performed for this task.

### Existing offline evidence and remaining tests

- Source-level tests cover Auth0 verifier fixtures, resolver denials, scripted lock-call ordering, project route/final reauthorization, UoW rollback/cleanup, provisioner permission checks, migration-runner control flow, catalog validators, and the guarantee that request startup does not invoke privileged admin preflight.
- `tests/postgres/test_live_authorization.py` contains guarded live PostgreSQL cases, including `test_inflight_authorized_operation_serializes_before_revocation`; its existence does not prove it passed. The selected test command below did not collect that live module.
- Missing live proof includes revoker-first ordering, stale snapshot behavior at the selected isolation level, the full set of identity/membership/grant insertion and revocation races, actual roles/ACLs and provider capabilities, RLS against both project logins, and the final migration/runtime ownership profile.
- No new Python tests were added: the coordination choices remain unapproved, and existing offline tests already exercise the source-level behavior. Adding a fake test for a future lock protocol would encode a proposal, not establish PostgreSQL semantics. New live cases are listed in `hosted-lock-isolation-test-matrix.md`.

**Decision:** continue local SQLite/stdio use and offline design/testing. Do not run migration 0010 or enable hosted multi-tenant serving until the product/security, storage, and database/provider gates above are resolved and the approved live evidence is recorded.
