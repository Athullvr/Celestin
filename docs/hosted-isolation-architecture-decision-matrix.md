# Hosted Isolation Architecture Decision Matrix

**Decision status: BLOCKED.** This is a source-grounded comparison, not an accepted architecture, provider assessment, migration authorization, live-test authorization, or hosted-service release gate. No option is approved by this document.

## Review baseline and evidence labels

The current checkout was `codex/celestin-core-memory-platform` at `5364221aeb7f7df32ae9ef458bcd370544ef14bd`; `git status --short --branch` showed a clean worktree and the branch 12 commits ahead of its configured upstream. The earlier source snapshot recorded inside the existing decision document is historical; this matrix uses the current checked-in source paths below. Orbit context retrieval for the repository's explicitly designated project `celestin` returned `ACCESS_DENIED`; it was not retried with another project.

Use these labels throughout:

- **SOURCE** — directly visible in current Python or migration source; not proof of deployed database state.
- **PROPOSAL** — a candidate design or policy, not approved.
- **LIVE REQUIRED** — requires a guarded test against an explicitly approved disposable PostgreSQL target.
- **PROVIDER UNKNOWN** — requires authoritative provider evidence for the selected host/configuration.
- **OWNER DECISION** — requires an explicit product/security or storage/database decision.

## Related contracts and evidence

- [Hosted authorization and revocation protocol](hosted-authorization-protocol.md)
- [Hosted lock-isolation decision record](hosted-lock-isolation-decision.md)
- [Hosted lock-isolation test matrix](hosted-lock-isolation-test-matrix.md)
- [Offline hosted provisioning readiness](hosted-provisioning-readiness.md)
- [PostgreSQL advisory-lock privilege-boundary proposal](postgres-advisory-lock-privilege-boundary-proposal.md)
- [PostgreSQL integration-test safety guide](postgres-integration-tests.md)

## Threat model

The alternatives are evaluated against the same threats:

1. Unauthenticated HTTP caller attempts protected work.
2. Authenticated principal lacks workspace, project, or action permission.
3. Application query omits a tenant predicate.
4. Caller can issue arbitrary SQL using a project-scoped runtime login.
5. Hosted application process is compromised or leaks credentials for multiple project logins.
6. Authorization-reader/admin, migration, database-owner, or provider-admin identity is compromised.
7. A long transaction, lock holder, pool leak, or retry causes denial of service or delays revocation.

Confidentiality/integrity, lock interference/availability, and authorization-revocation ordering are separate properties. RLS is not a control against arbitrary advisory-lock interference. A lock is not authentication or authorization evidence.

## Current source facts

- The hosted scope resolver rejects an invalid principal/action and checks principal activity, workspace/project lifecycle, membership or service status, explicit grant, and action permission before returning ResolvedProjectScope (src/orbit/mcp_server/hosted_scope.py::HostedScopeResolver.resolve, lines 268–365). Its execute method binds scope and calls the protected operation in the caller-owned transaction (lines 399–432).
- Hosted request composition first resolves a route in a control transaction, closes it, then acquires the exact configured project pool and repeats authorization in a project-login transaction before the handler runs (src/orbit/postgres/authorization.py::ProjectScopedPostgresHostedAuthorizationSessionFactory._execute_authorized_request, lines 433–519). There is no shared-role fallback in this class.
- The project login is mapped to one workspace/project in protected state keyed by session_user; migration 0008 installs project RLS policies around that map, and migration 0007 enables and forces RLS on the initial content tables (src/orbit/postgres/migrations/0008_project_scoped_runtime_roles.sql, lines 37–50 and 324–360; 0007_memory_request_rls.sql, lines 5–17). These are migration intentions, not live RLS results.
- Migration 0009's project lock function checks that session_user maps to the requested workspace before taking a workspace-scoped shared transaction lock (0009_project_request_lock_scope.sql, lines 38–69). It does not provide a project-specific key; projects in one workspace share this lock boundary.
- Migration 0008's reader and admin lock functions accept caller-supplied logical workspace/principal values (0008_project_scoped_runtime_roles.sql, lines 102–238). Migration 0009 removes project-runtime access to the reader wrapper, but the reader still has its caller-selected interface (lines 33–36). The admin wrappers remain logical-key interfaces.
- Migrations 0008–0009 do not revoke PUBLIC EXECUTE on built-in advisory-lock functions. The actual effective ACLs, owners, inherited grants, and provider ability to change them have not been inspected on a live database. The source proposal describes direct built-in calls as a cross-scope availability/serialization risk, not by itself a row authorization bypass.
- Request readiness intentionally rejects unverified reader/admin lock-key scopes and expects strict function profiles; _validate_function_catalog fails closed for the signatures in _UNVERIFIED_LOCK_KEY_SCOPE_SIGNATURES (src/orbit/mcp_server/hosted_server.py, lines 219–269 and 1318–1427). Request-pool readiness checks reader and project pools, not privileged provisioning (_assert_safe_hosted_pools, lines 1072–1075); tests/test_hosted_server.py::test_request_pool_readiness_does_not_run_privileged_admin_preflight protects that separation.
- The project request transaction sets a transaction-local statement_timeout when configured (src/orbit/postgres/authorization.py, lines 330–371). Settings include pool timeout 5 seconds, connection timeout 5 seconds, and statement timeout 10,000 ms by default (src/orbit/mcp_server/hosted_server.py::HostedRuntimeSettings, lines 391–407). Source does not set transaction isolation, lock_timeout, idle_in_transaction_session_timeout, or a whole-request deadline.
- The migration runner holds a session advisory lock on its migration connection and releases it in finally; each migration plus ledger row is transactional (src/orbit/postgres/migrations/runner.py::apply_migrations, lines 144–249; _lock/_unlock, lines 252–268). Its lock continuity and privileges have not been live-tested on the intended provider.
- Offline fake/catalog tests verify Python validation and call ordering, not PostgreSQL behavior. Existing tests include tests/test_hosted_server.py::test_authorization_reader_profile_fails_closed_for_unscoped_lock_wrapper, test_authorization_admin_probe_keeps_unscoped_lock_helpers_unready, and test_request_pool_readiness_does_not_run_privileged_admin_preflight; tests/postgres/test_request_unit_of_work.py::test_project_scoped_factory_authorizes_before_pool_selection_and_rechecks_on_project_login and test_project_transaction_rechecks_revocation_before_operation; and guarded live test source tests/postgres/test_live_authorization.py::test_inflight_authorized_operation_serializes_before_revocation. The latter's presence is not evidence it ran or passed.
- Local stdio/SQLite remains a separate supported path under the project rules (docs/celestin-loop-rules.md, “Compatibility and local mode”). None of the alternatives requires changing that path.

## Comparative architecture matrix

A–D are coordination/isolation designs. E is an environment choice that may enable an otherwise selected design; changing PostgreSQL hosts alone creates no tenant boundary.

| Evaluation axis | A. Scope-mapped advisory wrappers | B. Database-mediated authorization and lock operations | C. Transactional row-lock coordination | D. Database per project | E. PostgreSQL host with required admin capabilities |
|---|---|---|---|---|---|
| Unauthenticated caller / authenticated caller without grants | **SOURCE + LIVE REQUIRED:** none of these lock designs authenticates HTTP. Preserve the verified-token boundary and resolver/action checks; validate the full path live. | **SOURCE + LIVE REQUIRED:** same; a database operation must not turn caller-supplied claims into trusted identity. | **SOURCE + LIVE REQUIRED:** same; row locks do not authenticate or grant access. | **SOURCE + LIVE REQUIRED:** same; a database boundary does not replace request authentication or project authorization. | **NO DIRECT EFFECT:** host choice does not authenticate requests or grant project access. |
| Cross-project confidentiality and integrity | **SOURCE + LIVE REQUIRED:** protected session_user map/RLS is the intended defense against omitted predicates. Does not contain a compromised app process that can select multiple project DSNs. | **PROPOSAL + LIVE REQUIRED:** can derive scope and perform protected authorization changes from database state; a shared control credential still cannot prove which human the app intended unless the DB caller identity is distinct/trusted. | **PROPOSAL + LIVE REQUIRED:** retain RLS and explicit authorization; lock rows do not replace either. Must cover every mutable authorization fact and absent-row/insert cases. | **PROPOSAL + LIVE REQUIRED:** a database boundary narrows accidental cross-project SQL/RLS blast radius. A central compromised process holding all project DSNs can still cross databases. | **NO DIRECT EFFECT:** provider capabilities do not establish caller scope. Chosen database roles/RLS/application authorization remain necessary. |
| Advisory-lock interference and availability | **SOURCE + PROVIDER UNKNOWN:** project wrapper validates mapped workspace, but arbitrary built-in lock calls are not removed by migrations 0008–0009; actual ACL is unknown. Reader/admin wrappers accept caller-selected logical targets. A project can also hold its mapped workspace lock for a long transaction. | **PROPOSAL:** a narrow DB operation can avoid accepting raw keys and derive its lock set. If arbitrary built-ins remain callable, they can still interfere; the operation alone does not solve that. | **PROPOSAL:** removes Celestin request/revocation dependence on advisory locks only if request, writer, trigger, and migration coordination are all converted. Arbitrary advisory locks then should not block those Celestin paths; prove this live. | **PROPOSAL + LIVE REQUIRED:** expected to bound advisory interference to a project database, but cross-database behavior and the actual connection topology must be tested. It does not prevent DoS within that project. | **PROVIDER UNKNOWN:** verified ACL authority could permit restricting direct calls; it cannot stop a compromised permitted runtime from holding its authorized wrapper lock or long transaction. |
| Revocation under concurrency | **PROPOSAL + OWNER DECISION:** can serialize only if every protected request and authorization writer uses conflicting locks, locks are acquired before rechecking, and the selected isolation gives a fresh/aborted snapshot. Current transaction isolation is unspecified. | **PROPOSAL + OWNER DECISION:** strongest if the DB operation derives locks, rechecks authoritative rows, and mutates them atomically. Its caller identity, snapshot, lock order, and retry semantics still need specification. | **PROPOSAL + OWNER DECISION:** lock the authorization rows/anchors that requests read and revocation changes in a consistent order. Must cover missing grants, identity transitions, lifecycle rows, inserts, and triggers. | **PROPOSAL + OWNER DECISION:** per-project content DB cannot make a shared control-plane authorization change and a project request one cross-database transaction. Define propagation and request authorization freshness. | **NO DIRECT EFFECT:** a different host does not select isolation level or revocation policy. |
| Least-privilege role separation | **SOURCE MISMATCH:** desired readiness has no direct built-in lock grants for request roles, while current migration definitions do not establish that exact live profile; function owners are not explicitly assigned by 0008–0009. | **PROPOSAL:** narrow EXECUTE on fixed operations, non-login owner where appropriate, no raw-key API, and separate request/admin/migration identities. Requires safe ownership and grants. | **PROPOSAL:** request roles need only scoped row privileges; writers need authorization-table mutation privileges; migration identity remains separate. Exact RLS/trigger grants must be designed and tested. | **PROPOSAL:** one project login per project DB can reduce role scope, but control-plane/admin/migration identities remain privileged. | **PROVIDER UNKNOWN:** capability to create roles, manage memberships, inspect ACL metadata, and assign function owners must be proven for the selected configuration. |
| PostgreSQL/provider dependence | PostgreSQL-specific functions, ACLs, role identity, and RLS. | PostgreSQL-specific server-side functions/transactions and ACLs; a privileged function requires verified SECURITY DEFINER ownership/search_path and argument checks. | PostgreSQL row locking, transaction snapshots, RLS, and trigger semantics; does not inherently require advisory-function ACL changes. | PostgreSQL database provisioning and separate connection/configuration lifecycle per project. | Entirely provider/configuration dependent; no Neon compatibility claim is established here. |
| Operational complexity and cost drivers | Moderate shared-database operation, but provider ACL/owner work and shared control-plane risk remain. No price or performance estimate is verified. | High design/review burden for trusted functions, role ownership, function lifecycle, observability, and failure handling. | High one-time redesign and deadlock analysis; ongoing operation may avoid advisory ACL dependency. | Highest tenant-count-sensitive provisioning, connection pools, backups, monitoring, migration fan-out, restore, and reconciliation burden. No numeric break-even point is known. | Host change adds migration, operations, security review, and support work; no provider price or guarantee is asserted. |
| Migration and recovery | Forward migration must reconcile wrappers, built-in ACLs, owners, readiness, and runner lock continuity atomically or under an approved quiesced runbook. | Migrations must install/replace tightly scoped functions, grants, ownership, and exact recovery. Failure must leave the old safe profile or keep service disabled. | Forward migration must replace lock-sensitive request/writer/trigger paths and migration coordination; prove no mixed old/new locking window. | Provision/migrate projects independently, track partial rollout, restore and retry per project; cross-project migration orchestration is needed. | Must prove provider supports required operations and recovery before choosing a migration plan. |
| Testability and observability | Offline catalog fixtures can check validators. Live tests need distinct project, reader, admin, and migration logins; test direct built-in calls, wrapper scopes, ACLs, races, and rollback. | Offline tests can check function input/shape and app routing. Live tests must attempt forged scope/key input as each role and inspect actual function/role catalogs and concurrent mutation. | Offline tests can check SQL construction and intended lock order. Live independent sessions must test request-first and revoker-first, omitted tenant predicates, missing-row races, deadlock/timeouts, and migration coordination. | Live tests need at least two separate project databases/logins plus a control plane; prove isolation, revocation propagation, migration drift/recovery, and backup/restore behavior. | Run the selected full live matrix on the exact target/version/role profile; source fixtures are not provider evidence. |
| Compatibility with local SQLite/stdio | Compatible if hosted pools remain isolated from local server composition. | Compatible with the same separate hosted runtime boundary. | Compatible with the same separate hosted runtime boundary. | Compatible, but only in hosted mode. | Compatible if local runtime selection remains independent of PostgreSQL configuration. |

## Option-specific interpretation

### A. Scope-mapped advisory-lock wrappers

This best resembles the current project-login route, but the current implementation is not the proposed target: migration 0009's wrapper maps session_user to a workspace, not a project-specific lock key; reader/admin wrappers accept logical target arguments; migrations do not revoke built-in advisory PUBLIC EXECUTE; and source readiness rejects the reader/admin signatures while expecting stricter function profiles (hosted_server.py, lines 219–269 and 1318–1427). A future wrapper must derive or validate every scope from protected database state, never trust a GUC, request header, supplied principal label, or arbitrary key. SECURITY DEFINER without that proof would enlarge privilege. **A is not safe to select yet.**

### B. Database-mediated authorization and lock operations

This is distinct from a lock wrapper: the narrow database operation would derive affected identities/rows from persisted authorization state, acquire its own coordination, recheck conditions, and apply a mutation within one transaction. It could prevent callers from choosing arbitrary lock keys, but only if the exposed role cannot bypass the operation through direct lock APIs and cannot issue equivalent unauthorized table changes. A shared reader/admin login does not authenticate the human actor to PostgreSQL; the application trust boundary remains unless each caller has a distinct database-verifiable identity. **B needs a concrete caller/role model before it can be assessed as safer than A.**

### C. Transactional row-lock coordination

This avoids Celestin request/revocation reliance on advisory lock keys only after all participating paths are converted, including triggers, authorization writes, and migration-runner serialization. Locks must cover both present rows and stable rows that serialize absent grants or identities; all paths need one order and a defined stale-snapshot response. Arbitrary SQL can still consume resources and contend on rows it is permitted to access, but a raw advisory key should not interfere with a row-lock-only Celestin path. **C is a plausible provider-independent alternative, not a selected design; it requires broader implementation and live concurrency proof.**

### D. Separate database per project

This is the clearest database blast-radius boundary among the listed options when each project has distinct database credentials and the application cannot freely select credentials outside its authorized route. It carries a database-per-project operating model and does not solve compromise of a central process holding all project credentials. A shared control-plane authorization change and a project database request are not one atomic transaction; revocation needs bounded, explicit propagation or a synchronous per-request check. Consider D preferred only if product/security requires stronger project-level confidentiality or lock-interference boundaries and the storage/operations owners accept per-project migration, pooling, backup, restore, monitoring, and provisioning. If the goal includes surviving central-process compromise, D alone is insufficient; credential isolation or workload separation is also needed. **No capacity, cost, or provider limits are established here.**

### E. Different PostgreSQL host with required administrative capabilities

E is an enabling-environment choice, not a complete isolation architecture. A host that demonstrably supports exact built-in ACL/role/function-owner operations may make A or B feasible; it does not bind request identity, fix reader/admin scope, define revocation semantics, or mitigate a multi-credential application compromise. The current repository has no authoritative evidence that Neon supports the required operation. A host change must be evaluated on the actual PostgreSQL version, role model, ACL visibility/change authority, transaction support, recovery, and operational fit. **Do not select a provider based on generic PostgreSQL behavior alone.**

### Fallback if the selected provider cannot perform required ACL changes

If Neon cannot support the exact operations required by A or B, do not weaken the role profile or leave direct advisory calls available while claiming isolation. Evaluate C only as a complete conversion of request, authorization-writer, trigger, and migration coordination; evaluate D with its per-project operating and revocation-propagation costs; or evaluate E with authoritative capability evidence for the replacement host. If none is approved and passes its relevant live gates, keep hosted multi-tenant serving disabled and retain local SQLite/stdio.

## Revocation and timeout decision

### Current source behavior

The control transaction resolves a candidate route and closes before the project connection is acquired. The project transaction verifies its mapped session_user scope and repeats principal, membership/grant, lifecycle, and action checks before binding the request unit of work and invoking the handler. The project UoW and protected handler share that transaction (ProjectScopedPostgresHostedAuthorizationSessionFactory._execute_authorized_request; HostedScopeResolver.execute). Existing offline tests assert this ordering. They do not prove concurrent database snapshot behavior.

The checked-in decision record LI-02 describes “in-flight authorized operation completes before concurrent revocation commits; later request denies” as accepted documented intent, while also noting that a formal owner record was not located. Treat this as unconfirmed product policy, not approval.

### Proposed protocol — not approved

For either advisory or row-lock coordination:

1. Begin one protected request transaction using its project login.
2. Acquire all request-side coordination in the globally specified order before reading authorization facts.
3. Read current principal status, membership/service grant, project/workspace lifecycle, project grant, and action permission in that transaction. Bind RLS scope only after authorization.
4. Run the protected operation on the same transaction and hold the coordination through commit.
5. A revocation transaction acquires the conflicting writer coordination in the same key/row order before changing authorization state, then commits the change.
6. Commit is the revocation linearization point. If the request wins coordination first, it may finish and commit before the revocation. If revocation wins, the request must wait and then observe the revocation in fresh authorization reads, or the database must abort the stale transaction and the application must restart the whole authorization transaction before handler execution.
7. A request begun after revocation commit must deny. Immediate cancellation of already-running work is not implied and would require a separate cancellation/fencing design.

The selected transaction isolation must make step 6 true. The source does not set isolation; product/security and storage owners must choose and test the exact rule, such as fresh command snapshots at READ COMMITTED or abort/restart under a stronger isolation mode. Lock ordering alone is not proof.

### Timeout/failure policy remains open

Current source has pool/connection bounds and a statement timeout, but no configured lock timeout, idle-transaction timeout, or total request deadline. Owners must choose lock wait, statement, transaction/request, idle-transaction, cancellation, and retry limits from service objectives; this matrix invents no numeric thresholds. On timeout/cancellation before commit, the transaction should roll back and release locks. A connection loss during commit leaves the caller uncertain whether the mutation committed; recovery must re-read authoritative state in a new authorized operation. Do not automatically retry a write under unresolved delivery equality/idempotency rules.

## Decision and approval checklists

### Product/security owner — architecture approval

- [ ] Accept, reject, or amend the threat model, including the arbitrary-SQL project-login threat and compromised central process.
- [ ] Select A, B, C, D, or a reviewed combination; state residual confidentiality/integrity and availability risk.
- [ ] Decide whether revocation waits for in-flight requests or requires cancellation/fencing.
- [ ] Approve the transaction-snapshot/lock-ordering rule and timeout/cancellation/retry semantics.
- [ ] Set conditions under which D (one database per project) becomes preferred.
- [ ] Decide whether hosted service remains disabled if no option meets the threat model.

### Storage/database owner — architecture and implementation approval

- [ ] Specify the exact identities, authorization facts, lock/row set, and order used by every request, grant, revocation, trigger, and migration path.
- [ ] Select the isolation mode and fresh-read/abort behavior; define lock, statement, whole-request, and idle-transaction bounds.
- [ ] Define separate request-runtime readiness and privileged provisioning/migration preflight profiles.
- [ ] Approve forward-only migration, atomicity/quiescence, rollback, recovery, and observability requirements.
- [ ] Confirm how local SQLite/stdio remains independent.

### Provider/database administrator — capability evidence

- [ ] Identify the exact provider service, PostgreSQL version, compute/role model, and database boundary under review.
- [ ] Provide authoritative evidence or guarded verification for required role membership, function ownership, ACL inspection, grantor/grant-option/effective privilege checks, and exact advisory-function ACL changes, if A/B depends on them.
- [ ] Establish whether the required operations can share the migration/ledger transaction; if not, approve a quiesced operator and recovery procedure.
- [ ] Confirm an explicitly identified fresh disposable target and distinct test identities before separate live-test authorization.

### Separate authorization to run live tests

Architecture approval does not authorize database access. Before any live test, the task owner must separately authorize the exact disposable target and test operations; its identity and freshness must be positively verified by the existing safety guard; roles must match the intended request path; and no production/unknown target may be used. No such approval or verification is claimed here.

## Required evidence before any architecture gate can pass

- Explicit product/security and storage-owner decisions above.
- For A/B, authoritative provider evidence for ACL, role, ownership, and transaction/recovery capabilities; for C, an implemented full row-lock protocol and proof that no Celestin request, trigger, writer, or migration path still relies on advisory locks; for D, an approved operating/cost model and revocation propagation design.
- Reconciled source readiness expectations and migration definitions; no test fixture should be weakened to match existing DDL.
- Offline tests for application contracts plus live tests on the approved disposable target for role/ACL/RLS behavior, direct lock interference, each revocation race direction, transaction isolation, timeouts, pool cleanup, migration rollback/retry, and cross-project attempts.
- Separate release approval after the evidence is reviewed.

## Decision

**BLOCKED — no preferred architecture is justified by the current evidence.** A is closest to the existing project-pool shape but depends on unresolved provider ACL/ownership capabilities and unresolved reader/admin scope. C avoids that provider-specific ACL dependency only after a broader redesign that includes the migration runner. D is a stronger project boundary if its operational model is accepted but does not contain a compromised central process holding all credentials. E only supplies a possible execution environment and is not an isolation design by itself.

Until product/security, storage/database, and provider prerequisites are resolved and verified, keep hosted multi-tenant serving disabled and retain local SQLite/stdio. No migration 0010 is created or authorized by this review. D-08 delivery equality/replay is independent and remains outside this decision.
