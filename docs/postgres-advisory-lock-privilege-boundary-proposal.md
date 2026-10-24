# PostgreSQL Advisory-Lock Privilege Boundary — Forward-Only Proposal

**Status: proposal only. No migration has been written or applied, and no PostgreSQL catalog was inspected for this report.** The hosted tenant-isolation gate remains open.

## Verified source boundary

Migrations `0008_project_scoped_runtime_roles.sql` and `0009_project_request_lock_scope.sql` define project, reader, and authorization-write wrappers around `pg_catalog.pg_advisory_*` functions. The lock wrappers in those migrations are invoker-security. Their wrapper `EXECUTE` grants are restricted, but the built-in functions have default `PUBLIC EXECUTE`; revoking a wrapper grant cannot remove that inherited privilege. A project-login holder that can run arbitrary SQL can therefore call built-ins directly and interfere with the authorization lock namespace. This is an availability and serialization attack; the protected `session_user` scope map remains the row-isolation boundary.

The source-level readiness code in `src/orbit/mcp_server/hosted_server.py` now checks all catalog-visible `pg_catalog` functions whose names start with `pg_advisory_`. It separately validates effective execution, a direct ACL entry for the current login, and `PUBLIC EXECUTE`, requiring an exact reviewed function roster. It also validates the project, reader, and authorization-admin wrapper definitions, including owner, role attributes, language, volatility, security mode, fixed `search_path`, body, public access, current-role access, and unexpected execute grants. Missing rows or non-boolean catalog metadata fail closed.

The authorization-admin validator is callable as `_assert_safe_authorization_admin`; the hosted MCP runtime intentionally has no authorization-admin pool, so it does not invoke this check during request startup. The opt-in live role-profile test invokes it on the dedicated admin test login. A future provisioning process must run the same check before using an admin credential; no production provisioning host is currently wired here.

The privileged-group roster validator accepts only the three expected `NOLOGIN`, non-superuser, `NOBYPASSRLS`, non-privileged, `INHERIT` groups with no parent memberships and an exact, explicitly supplied direct-login roster without `ADMIN OPTION`. The live catalog test obtains the full roster using the migration/test-owner connection. Per-login readiness separately checks the current reader, admin, or project login's own memberships and effective privileges.

The migration runner acquires a session-level `pg_advisory_lock(bigint)`, applies each migration and ledger row in a transaction, and releases the session lock in `finally` using `pg_advisory_unlock(bigint)`. Request and authorization-write locks are transaction-scoped and release on commit or rollback. Connection-pool reset clears session state, but no live behavior is established by this proposal.

## Threat model

| Caller / failure | Current boundary and impact | Proposed boundary / residual risk |
|---|---|---|
| Unauthenticated HTTP caller | Auth middleware is intended to reject before the hosted handler; this proposal does not revalidate the Auth0 path. | No database identity should be selected. Auth middleware remains a separate required gate. |
| Authenticated principal without workspace/project access | Application resolution and project-login mapping/RLS are intended to deny the request. | Advisory ACL changes do not replace resolver checks or RLS. Cross-scope reads/writes still require live acceptance tests. |
| Query bug omitting a tenant predicate | Forced RLS compares rows with the `session_user`-bound project scope. | Preserve and live-test RLS; this advisory change is defense-in-depth for lock control, not a change to row isolation. |
| Caller with arbitrary SQL on a shared project runtime credential | Default `PUBLIC EXECUTE` exposes all advisory built-ins, allowing arbitrary-key session or transaction locks and cross-scope lock interference/DoS. | Revoking `PUBLIC` for only the advisory built-ins and denying direct runtime privileges prevents raw-key calls. The project wrapper still permits a lock only for its mapped workspace; a caller can hold that scoped shared lock in an open transaction and delay workspace authorization writers. |
| Compromised auth-reader/admin credential | These are trusted cross-project control-plane identities and their wrapper APIs can lock arbitrary *logical* workspace/principal keys; the admin can also mutate authorization data. | Least-privilege wrapper grants contain built-in access, but do not make compromised control-plane credentials safe. Rate-limit, audit, revoke, and isolate these credentials. |
| Compromised application process, database owner, provider administrator, or leaked credentials | A central application process can select among configured project credentials; database administration can bypass application/RLS boundaries. | Not mitigated by advisory wrappers. These identities remain explicitly trusted; stronger isolation requires deployment or database separation. |

## Required lock and role profile

The catalog check expects these 21 currently reviewed overloads:

| Family | Signatures |
|---|---|
| Session exclusive | `pg_advisory_lock(bigint)`, `pg_advisory_lock(integer,integer)` |
| Session shared | `pg_advisory_lock_shared(bigint)`, `pg_advisory_lock_shared(integer,integer)` |
| Session unlock | `pg_advisory_unlock(bigint)`, `pg_advisory_unlock(integer,integer)`, `pg_advisory_unlock_shared(bigint)`, `pg_advisory_unlock_shared(integer,integer)`, `pg_advisory_unlock_all()` |
| Transaction exclusive | `pg_advisory_xact_lock(bigint)`, `pg_advisory_xact_lock(integer,integer)` |
| Transaction shared | `pg_advisory_xact_lock_shared(bigint)`, `pg_advisory_xact_lock_shared(integer,integer)` |
| Session try-lock | `pg_try_advisory_lock(bigint)`, `pg_try_advisory_lock(integer,integer)`, `pg_try_advisory_lock_shared(bigint)`, `pg_try_advisory_lock_shared(integer,integer)` |
| Transaction try-lock | `pg_try_advisory_xact_lock(bigint)`, `pg_try_advisory_xact_lock(integer,integer)`, `pg_try_advisory_xact_lock_shared(bigint)`, `pg_try_advisory_xact_lock_shared(integer,integer)` |

The proposed post-change login profile is:

| Login / group | Direct built-in ACL | Effective built-in access | `PUBLIC EXECUTE` on built-ins | Intended wrapper entry points and lock scope |
|---|---|---|---|---|
| Project-specific login / `celestin_project_runtime` | None | None | None | `celestin_lock_project_authorization_request(uuid)` only. It derives the workspace from the protected `session_user` mapping, rejects a mismatched workspace, then takes a shared transaction lock. |
| Authorization-reader login / `celestin_authorization_reader` | None | None | None | `celestin_lock_authorization_request(uuid,text,text,text)`; shared transaction locks for workspace and principal, sorted consistently with writers. This role is a trusted control-plane identity, not a tenant credential. |
| Authorization-admin login / `celestin_authorization_admin` | None | None | None | The four `celestin_lock_*_authorization_write` / principal-transition helpers; exclusive transaction locks. The admin remains trusted to mutate authorization across scopes. |
| Migration/database-owner login | Only `pg_advisory_lock(bigint)`, `pg_advisory_unlock(bigint)`, `pg_advisory_xact_lock(bigint)`, and `pg_advisory_xact_lock_shared(bigint)` | Exactly those four | None | The first pair protects the migration runner's session; the transaction pair is required by database-owner-owned `SECURITY DEFINER` wrappers and is usable by the owner while executing them. |
| Three `NOLOGIN` group roles | None | None | None | Wrapper grants only, inherited by their separately provisioned logins. They must not receive built-in advisory execution. |

The role profiles above are post-change targets. For every login, the validator must check the effective privilege, direct grantee ACL, and `PUBLIC` ACL independently; a login-level revoke cannot cancel a `PUBLIC` grant.

Trigger functions are invoked by database triggers and receive no direct execute grant to the three runtime groups. They and the lock wrappers must be owned by the verified database owner, which must not be a superuser, `BYPASSRLS`, role creator, database creator, replication role, or member of an unexpected role. The owner's ability to execute the required built-ins after a `PUBLIC` revoke must be established explicitly.

The source validator currently accepts a migration role with exactly the four built-in privileges above. The live role-profile query checks every overload's effective, direct, and `PUBLIC` ACL state. The live suite also attempts representative direct lock calls as both project logins; it has not been run against PostgreSQL.

## Alternatives and recommendation

1. **Per-login `REVOKE` only — insufficient.** PostgreSQL privileges are additive: a login-level revoke cannot cancel `PUBLIC EXECUTE`. It does not close the arbitrary-SQL path.
2. **Restricted Celestin wrappers without built-in revocation — insufficient.** An arbitrary SQL caller can bypass the wrapper and invoke the public built-in directly.
3. **Revoke every function in `pg_catalog` — reject.** That changes unrelated catalog-function behavior far beyond advisory locks.
4. **Revoke `PUBLIC EXECUTE` from only advisory-lock overloads on a dedicated Celestin database — recommended conditionally.** It closes the shared-credential direct-call path while containing the global ACL change to a database reserved for Celestin. It still requires a database/provider administrator with authority over the built-in function ACLs, an inventory of database principals and dependent workloads, and explicit review of any grants that must be restored. Do not use this on a database shared with unrelated applications without a complete impact and recovery plan.
5. **Separate database per tenant — stronger blast-radius control, higher cost and operations.** This also contains advisory-lock interference, but adds database provisioning, migrations, connections, backups, and monitoring per tenant. It is a product/operations choice rather than a patch to the current role model.

The recommended boundary trusts PostgreSQL/provider administration, the migration owner, the authentication/control-plane process, and the hosted application process. It does not protect against a compromised database superuser, provider administrator, migration owner, or central application process that can select another configured project credential. The authorization-reader and admin wrapper interfaces still accept caller-selected logical workspace/principal values and can be abused by a compromised control-plane credential to cause lock contention within Celestin's lock namespace; they do not accept raw advisory keys. Reducing that availability risk further requires a separate control-plane threat-model decision.

## Forward-only change outline — not executable or approved

Do not edit migrations 0001–0009. If approved, add a new forward migration after 0009 (next repository migration version at implementation time). Prefer one transaction containing the wrapper replacements, wrapper ACL changes, built-in `PUBLIC` revokes, and the four owner grants. This requires an execution identity authorized to alter the system-function ACLs while also applying/recording the migration. The existing non-superuser migration/test identity is not proven to have that authority, and the live-test target guard must not be weakened to permit an unknown privileged connection. A provider-controlled administrative migration path must be specified first. If that provider cannot make the changes atomically with the ledger, an explicitly quiesced, separately reviewed operator procedure is a fallback with a larger recovery window. This outline is not a runnable migration.

1. **Preflight:** require the existing expected advisory function set or fail; enumerate the current function owners, `PUBLIC` ACL entries, direct ACL entries, function execute grant options, database users, and any non-Celestin workload using advisory locks. Confirm that the operator can change every targeted built-in ACL. The current migration test role is deliberately non-superuser; repository evidence does not establish that it can revoke ACLs on PostgreSQL-owned built-ins. Do not weaken the test identity or grant it broad permanent privileges to make the migration pass.
2. **Define/replace wrappers:** use `CREATE OR REPLACE FUNCTION` for the reader request lock, mapped-project request lock, four admin write locks, and two trigger functions. Also update the two project scope-match helpers' path. Set request/admin wrappers to `SECURITY DEFINER` only where needed; keep scope-match functions invoker-security. Set every function path to `pg_catalog, pg_temp`, use `pg_catalog.*` for built-ins, and schema-qualify every application object (`public.*` or `celestin_private.*`). The project lock helper must continue to compare `session_user` and the requested workspace with the protected mapping before acquiring the mapped workspace lock. No project-facing helper may accept a raw lock key. Preserve the canonical key construction and sorted lock order validated by `hosted_server.py`.
3. **Constrain wrapper ACLs:** revoke wrapper execute from `PUBLIC` and unrelated roles; grant only the reader wrapper to `celestin_authorization_reader`, the project wrapper to `celestin_project_runtime`, and four write wrappers to `celestin_authorization_admin`. Trigger functions remain trigger-only. Preserve the expected database-owner function ownership and check `proconfig`, `prosrc`, `prosecdef`, and execute ACLs after replacement.
4. **Built-in ACL operation:** revoke `EXECUTE` from `PUBLIC` for each catalog function matching the reviewed `pg_advisory_` prefix, not for all of `pg_catalog`. Grant the four bigint functions in the role matrix directly to the verified database-owner/migration identity. Do not grant integer-pair, `try_*`, shared session, unlock-all, or other direct built-ins to request or admin logins. The chosen operator path must apply these ACLs and the migration ledger atomically if supported; otherwise, keep the hosted runtime quiesced across the explicit two-step change and document recovery for failure between steps.
5. **Migration-runner continuity:** the runner acquires its session lock before applying migrations and releases it in `finally`. Ensure its login has both session lock and unlock privileges before the migration can remove `PUBLIC`; transaction rollback must leave the pre-change ACL intact so the runner can unlock after failure. On success, the direct session grants must be committed before the runner's final unlock. A retry after partial external/manual ACL work must first inspect actual catalog state; never assume the ledger alone proves ACL state.
6. **Deployment ordering:** disable hosted readiness and stop/drain hosted request and control-plane pools. Apply the reviewed wrapper and ACL changes. Verify all roles and function ACLs from distinct logins, run the live acceptance suite, then restart with hosted mode still disabled until a human release gate approves. Do not run this on an unknown or shared database.

An illustrative catalog loop for the `PUBLIC` revoke is shown below only to make the intended target clear. It must be syntax-checked and reviewed for the supported PostgreSQL/provider version before use; it does not establish that the executing role has the authority to alter built-in ACLs:

```sql
DO $celestin_advisory_acl$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT procedure.proname,
               pg_catalog.pg_get_function_identity_arguments(procedure.oid) AS identity_arguments
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
         WHERE namespace.nspname = 'pg_catalog'
           AND pg_catalog.left(procedure.proname, 12) = 'pg_advisory_'
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE EXECUTE ON FUNCTION pg_catalog.%I(%s) FROM PUBLIC',
            target.proname,
            target.identity_arguments
        );
    END LOOP;
END;
$celestin_advisory_acl$;
```

The role-specific `GRANT EXECUTE` statements must name the four exact bigint signatures in the matrix and target the verified database owner. The migration and operator procedure must fail atomically if an overload, role, owner, or required grant is absent or unexpected. The ordinary migration runner currently executes migration SQL and its ledger insert in one transaction but is not proven to possess the authority needed for this catalog ACL operation.

## Rollback and upgrade limits

- The change is forward-only: migrations 0008 and 0009 may already be applied and their checksums are immutable.
- A failed transactional migration should roll back wrapper DDL, ACL changes, and its ledger row together. The runner's `finally` must still be able to unlock; test this against a disposable server using the exact target role.
- If a provider forces ACL changes outside the migration transaction, hosted mode must remain quiesced across both steps. A failure between them is a recovery incident, not an automatic downgrade.
- Do not restore blanket `PUBLIC EXECUTE` as a rollback. It reopens direct arbitrary advisory-lock access. Restore any unrelated workload access only from a pre-change, owner-reviewed ACL inventory and grant plan.
- A forward repair can restore approved per-role grants or adjust wrappers. Whether built-in ACL ownership is transferable or grantable on the chosen provider is an external decision and cannot be inferred from the checked-in SQL.

## Required verification before considering live testing

### Offline source checks

- Expected and mutated advisory catalog profiles for all 21 overloads, including effective, direct-login, and `PUBLIC` execution.
- Missing function rows, unknown overloads, duplicate rows, short rows, and `NULL` privilege metadata all fail closed.
- Admin function profile validates all four helper bodies, common safe owner, `SECURITY DEFINER`, fixed search path, no public grant, intended execution, and no unexpected grant.
- The three privileged group roles and exact direct roster reject login-enabled/elevated groups, parent memberships, missing/extra logins, `ADMIN OPTION`, elevated login members, duplicate rows, and missing catalog values.
- Hosted runtime/SQLite and public MCP schema regression tests remain unchanged.

### Live checks on an explicitly approved fresh disposable PostgreSQL database

- Before migrations, verify exact database/server identity and five distinct non-superuser test logins through the existing guarded fixture.
- Apply reviewed migrations only through the explicit runner or separately reviewed privileged operator procedure.
- Check all 21 overload ACLs as migration, auth-reader, auth-admin, project A, and project B logins; verify exact `PUBLIC`, direct, and effective profiles.
- Inspect ownership, `SECURITY DEFINER`, `search_path`, bodies, wrapper grants, protected role roster, schema ownership/CREATE, and RLS grants/policies.
- As both project logins, assert every direct built-in call family is denied (not only representative bigint calls), while the mapped project wrapper succeeds for the mapped workspace and rejects another workspace.
- Exercise reader/admin wrappers and authorization revocation races in independent transactions; verify locks release after commit/rollback and a failed migration can still release the session migration lock.
- Verify pool reset releases session locks and settings; verify cross-project read/write isolation continues to hold with an omitted tenant predicate.

No live test, migration, SQL command, Auth0 request, deployment, credential change, or external service operation has been performed for this proposal. Source-level checks do not pass the hosted tenant-isolation gate.

## Implementation design addendum — proposal only

This addendum clarifies the trust boundary and separates the login that runs migrations from the identity that owns privileged lock functions. It is not an approval, provider capability claim, or migration specification. If it conflicts with the earlier role table, treat the role separation below as the proposed target and keep the implementation gate closed until it is reviewed.

### Current migration versus readiness profile

This comparison is source-level only; no catalog state was queried. The readiness definitions in `src/orbit/mcp_server/hosted_server.py` are stricter than migrations 0008–0009:

| Object/profile | Migration 0008–0009 | Source readiness expectation | Result |
|---|---|---|---|
| Reader request-lock wrapper | Migration 0009 replaces it as `SECURITY INVOKER` with `search_path=pg_catalog`. | `_function_specs(project_runtime=False)` expects `SECURITY DEFINER` and exactly `search_path=pg_catalog, pg_temp`; `_UNVERIFIED_LOCK_KEY_SCOPE_SIGNATURES` then rejects the caller-selected keys regardless. | Not ready; changing only the security mode/path would not fix the scope flaw. |
| Project request-lock wrapper | Migration 0009 defines it as `SECURITY INVOKER` with `search_path=pg_catalog, celestin_private`; it verifies `session_user` against the protected workspace mapping before locking. | Project readiness expects `SECURITY DEFINER` and exactly `search_path=pg_catalog, pg_temp`, plus the reviewed body and owner profile. | Scope check exists, but catalog profile differs; any change must preserve the check and prove the definer owner's table/RLS access. |
| Authorization-write wrappers | Migration 0008 creates the four helpers as invoker-security without a fixed `search_path`; their logical lock inputs are caller-selected. | Admin readiness expects `SECURITY DEFINER`, exactly `search_path=pg_catalog, pg_temp`, a reviewed owner and body, and still fails closed for their unverified scope signatures. | Not ready; do not promote them by copying the readiness template. |
| Request-scope helper functions | Migration 0008 uses stable SQL functions with `search_path=pg_catalog, celestin_private`. | Project readiness expects stable invoker SQL functions with `search_path=pg_catalog, pg_temp` and exact source bodies. | Exact configuration differs; verify whether every relation reference can be schema-qualified before changing the path. |
| Trigger functions | Migrations 0008–0009 define security-definer functions with `search_path=pg_catalog, public`; migrations create the expected trigger names/events, and 0009 revokes direct execution from the protected groups. | Trigger readiness expects `search_path=pg_catalog, pg_temp`, database-owner ownership, exact body/security profile, exact attachment/timing/events, enabled state `O`, and no unexpected execution grants. | Path/ownership profile differs or is not established by SQL; migration source matches the tested attachment/body roster, but only a live catalog can establish enabled state and effective grants. |
| Function ownership | The migrations do not explicitly `ALTER FUNCTION ... OWNER`; new functions are owned by the role that executes the migration. | Readiness requires the function owner to be the database owner and rejects elevated attributes or unexpected memberships. | Depends on the actual migration identity and provider role model; not verified from a database. |
| Celestin wrapper grants | Migrations revoke wrapper execution from `PUBLIC`, then grant the project, reader, or admin role as applicable; 0009 removes project execution from the reader wrapper. | Readiness checks exact effective/direct grants, no `PUBLIC`, no unexpected execution grants, and grantability metadata. | Checked-in intent is partly aligned, but actual ACL/grantor/grant-option state remains unverified. |
| Built-in advisory functions | Migrations 0008–0009 do not revoke `PUBLIC EXECUTE` from the `pg_catalog.pg_advisory_*` overloads. | Request profiles require no effective, direct, or `PUBLIC` execution; the source's `migration` profile permits only four direct bigint overloads. | The current database-wide public privilege remains a live prerequisite; source fixtures cannot establish provider authority to change it. |

The checked-in source tests compare trigger bodies and trigger clauses to the readiness expectations, and catalog-fixture tests reject altered trigger profiles. They do not execute the migrations or verify that PostgreSQL assigns the expected owners, grants, enabled state, or search-path catalog configuration.

### Threat classification and trusted lock scope

The project wrapper in migration 0009 checks `session_user` against the protected `celestin_private.project_runtime_scopes` mapping before taking the workspace lock. This is the only current request-lock wrapper whose scope is verified by database state. Do not replace that check with a caller-settable GUC or a request header. A project credential may hold its one mapped workspace lock for as long as the transaction stays open, including while idle. The request UoW configures transaction-local `statement_timeout`; source inspection found no `lock_timeout` or `idle_in_transaction_session_timeout` setting. Define and test lock-wait and transaction/idle-transaction bounds as separate availability controls; they do not substitute for scope validation.

The reader and authorization-admin wrappers accept logical workspace or principal values from their caller. Those are not raw numeric advisory keys, but the wrapper hashes them into lock keys; the caller can still choose which logical lock to contend on. A `SECURITY DEFINER` declaration would increase the impact unless the function first establishes a database-verifiable binding. The current global reader/admin login cannot prove from `session_user` which authenticated human or workspace administrator the application intended. Keep their readiness closed. Do not make them ready merely by changing `SECURITY INVOKER` to `SECURITY DEFINER` or by passing a “verified” identity string.

Before reopening those paths, choose and test one of these designs:

1. **Database-bound scoped credentials:** map each login to a scope in protected database state, then derive or validate every lock target from that mapping. This is strongest for project-runtime logins; applying it to a global reader/admin identity has substantial provisioning and credential-scaling costs.
2. **Database-mediated authorization operation:** expose a narrow operation that derives impacted rows and lock targets from persisted state and performs authorization checks and the protected change in the same transaction. It must not accept an arbitrary hash/key or trust a caller-supplied reviewer/principal label as authentication. Specify the executor identity and concurrency ordering before granting it.
3. **Row-lock redesign:** replace advisory locking with locks on the actual authorization rows read by a request and changed by revocation. This requires proving that every mutable authorization fact is locked in a consistent order and that existing triggers cannot introduce a lock-order cycle.

The smallest secure v1 is not yet selected. Until one is approved and implemented, retain `_UNVERIFIED_LOCK_KEY_SCOPE_SIGNATURES` and fail closed for reader/admin lock helpers. A compromised reader/admin credential can already expose authorization metadata or mutate grants according to its grants; arbitrary logical locks add a cross-scope availability risk. This role compromise is a control-plane trust failure, not tenant isolation supplied by RLS.

Current authorization keys are logical typed tuples serialized by PostgreSQL and hashed with `hashtextextended` under the `celestin-auth-v1:` prefix. Request and writer paths must use exactly the same serialization, version prefix, seed, and stable key ordering for the same logical workspace/principal; acquire multiple keys in sorted order. The type tags separate logical workspace and principal keys before hashing. Hash collisions in a 64-bit key space can cause unrelated operations to block each other; they do not authorize data access and must be treated only as false contention. The migration runner currently uses the fixed `MIGRATION_LOCK_KEY` with the one-`bigint` advisory-lock overload. Its numeric key is a separate logical purpose, but the source does not prove a collision-free namespace against hashed application keys. Do not change either representation during an ACL migration without a coordinated runner upgrade and an explicit compatibility plan.

### Confidentiality, integrity, and availability

| Failure or attacker | Confidentiality/integrity consequence | Availability consequence |
|---|---|---|
| Unauthenticated HTTP request | Existing hosted authentication must reject before protected tool execution or database selection. | Request flood remains an edge/application rate-limit concern. |
| Authenticated user lacking a project grant | Authorization resolution and project RLS must deny access; advisory locks are not authorization evidence. | Repeated denied requests can consume bounded resources. |
| Tenant predicate omitted by an application query | The `session_user`-bound forced-RLS policy is intended to contain the query; live proof is still required. | Incorrect queries can consume resources within the selected project. |
| Project login holder with arbitrary SQL | A lock alone does not grant row access or bypass RLS; the protected login-to-scope mapping remains the row boundary. | Public built-in advisory execution permits arbitrary lock interference until its ACL is restricted; even a scoped project wrapper can delay its mapped workspace. |
| Reader/admin credential or application process compromise | The reader/admin roles are cross-scope control-plane identities; application credentials for multiple projects can select those projects. This design does not contain such a compromise. | Caller-selected reader/admin wrapper keys can block unrelated logical scopes; lock exhaustion and long transactions remain risks. |
| Migration/provider-owner compromise or failure | Can alter schema, role grants, function owners, or policies; outside request RLS protection. | Can block migrations or destabilize every Celestin role. |

Revocation ordering is valid only if the request rechecks principal status, membership/grant, project lifecycle, and action permission after acquiring the agreed lock/row-lock boundary and holds that boundary through commit. The writer must acquire the conflicting lock before protected authorization changes. Which transaction wins is determined by lock acquisition order; state that ordering and exercise both race directions in live disposable tests. An advisory lock is not a substitute for the in-transaction authorization recheck.

### Readiness contracts and identities

Request readiness and privileged preflight are independent contracts. The current `HostedDatabasePools` contains the authorization-reader control pool and configured project pools. `_assert_safe_hosted_pools`, called during hosted lifespan startup and `/readyz`, checks only those request pools. It does not have an admin or migration pool and must not provision roles, change ACLs, or run migrations. `celestin-migrate` calls the explicit migration runner; `PostgresAccessProvisioner` and `ProjectDatabaseLoginRegistry` use separately supplied authorization-admin connections. No production privileged preflight composition is wired here.

| Identity | Proposed responsibility | Proposed direct built-in advisory privileges | Readiness and trust boundary |
|---|---|---|---|
| Project runtime login | Serve one mapped project/workspace. | None. Use only the project wrapper after its `session_user` mapping check. | Request readiness; not a provisioning identity. |
| Authorization-reader login | Read authorization state for request resolution. | None. Its lock interface remains unresolved and unready until scope is database-bound or locking is redesigned. | Request readiness can check the role profile, but must fail closed while its wrapper contract is unsafe. This is a trusted global control-plane credential. |
| Authorization-admin login | Perform explicitly authorized membership/grant changes. | None. Do not expose arbitrary-key wrappers. | Separate privileged preflight; do not put this DSN in the ordinary MCP process. |
| Migration executor login | Run the explicit migration runner on its dedicated connection. | At minimum, the runner's exact session `pg_advisory_lock(bigint)` / `pg_advisory_unlock(bigint)` pair must remain usable for the whole migration transaction. | Operator-only. The current source validator expects four privileges under its `migration` profile; separating this profile is a future code/readiness change, not a fact about a live deployment. |
| Lock-function owner | Own narrowly reviewed `SECURITY DEFINER` wrappers/triggers, if the approved design uses them. | Only the transaction-lock overloads actually invoked by owned functions. | Prefer a non-login, non-BYPASSRLS owner with the minimum table/schema rights. Exact role attributes, RLS behavior, and ownership must be validated against PostgreSQL/provider semantics before use. Do not assume this is the migration login. |
| Provider/database administrator | Perform provider-controlled role/function ACL operations that the migration executor cannot perform. | No application request privilege. | External operator identity, separated from both MCP runtime and ordinary migration credentials. Provider capability is unresolved. |

The current source validator merges the migration runner and function-owner profile into one “migration” profile that allows four bigint overloads. `_validate_function_catalog` also requires wrapper/trigger owners to be the database owner. A reviewed implementation should split these profiles if the identities are separated: runner session lock/unlock versus function-owner transaction locks. It must decide whether the dedicated owner can itself be the database owner and how the migration executor may create/replace those functions without granting unsafe role membership; the current readiness code does not establish that separation. Any change must also ensure the runner can still release its session lock after a failed migration and can reacquire it for retry. Do not grant a login extra lock functions just to satisfy a fake-catalog fixture.

### Forward-only migration 0010 concept and recovery gate

`0010` is a placeholder for a future next-numbered migration, not a created file or an approved name. It must not be written until both the scope-binding design and provider/operator execution path are approved.

**Preflight must fail closed** unless it can inspect the complete supported overload roster, function owner identities, all direct and `PUBLIC` ACL entries, grantors, grant options, effective privileges for every relevant login, role memberships, wrapper definitions/owners/configuration/grants, trigger catalog, and the exact migration ledger/version. It must verify the required operator can perform every planned change before any DDL or ACL statement is issued. An incomplete or unknown catalog state is a blocker, not permission to broaden grants.

**Atomic path:** use the existing runner's session lock on the same connection that applies migration SQL and inserts its ledger row. The runner uses autocommit and one transaction per migration. `0010` must retain the runner's lock and unlock capability before revoking anything; wrapper-owner transaction privileges must be granted to the verified function owner before wrappers depend on them. ACL, function/trigger definitions, role grants, and ledger insert should commit or roll back as one transaction. On rollback, the pre-migration ACL and ledger remain; the runner's `finally` still unlocks on the same session. If the connection dies, PostgreSQL releases its session lock; retry begins with catalog reinspection and the ledger/checksum guard. The exact provider permissions and transactional behavior are unverified.

If Neon/provider administration requires a separate ACL operation that cannot be done in the runner's transaction, do not pretend this is atomic. The fallback would require a separately approved, quiesced operator runbook: drain request/control-plane pools, capture an owner-reviewed exact ACL/role/ownership inventory, acquire the same migration exclusion, apply the provider step and migration under a documented recovery protocol, verify catalog state from each distinct login, then run the live gate before serving. Failure between steps is an incident requiring forward repair from the recorded inventory; never blanket-restore `PUBLIC EXECUTE`. If the provider cannot make the required operation safely, stop and choose another architecture (such as a dedicated Celestin database with provider-managed ACLs or a reviewed design that avoids direct advisory built-ins). Do not weaken row isolation.

### Independent readiness and test gates

1. Keep local stdio/SQLite as-is; keep hosted mode disabled until all request readiness checks and security review pass.
2. Add offline tests only for source-enforced behavior: exact catalog fixtures, fail-closed metadata, wrapper scope guard, and the fact that request-pool readiness never calls privileged provisioning readiness. Such tests validate application contracts and fixtures only, not PostgreSQL/Neon ACL semantics.
3. Add an independently operated privileged preflight only after its login, owner, role roster, recovery mechanism, audit path, and secret source are approved. It must not be called by hosted request startup.
4. On an explicitly approved, fresh disposable database, use distinct migration, reader, admin, and two project logins. Verify identities before any migration. Then apply the reviewed forward migration through the approved runner path and assert every overload's ACL, wrapper/trigger catalog, role membership, RLS state, both cross-project read/write directions, revoke/request race order, timeout/cancellation, rollback, and runner lock release/retry behavior.
5. Record a live result only after the guarded tests actually run against the approved target. Fake catalog rows and source inspection are not live validation.

### Unresolved provider and product questions

- **Provider capability:** Which PostgreSQL version/Neon compute and role is used? Can the approved operator revoke `PUBLIC EXECUTE` on each exact `pg_catalog.pg_advisory_*` overload and grant only selected overloads to named Celestin roles? Are those operations permitted within the same transaction that applies schema DDL and the migration ledger?
- **Function/role ownership:** Can the provider create and retain the required non-login, non-BYPASSRLS function owner and grant it only the needed built-ins? Which exact role can create/replace functions, set owners, inspect all ACL/grantor metadata, and restore a prior reviewed ACL?
- **Role administration:** Which operator creates the three NOLOGIN groups and distinct logins, sets exact direct memberships without `ADMIN OPTION`, and manages rotation/revocation? Can the runtime/migration roles mutate that roster? They should not.
- **Database blast radius:** Is the database dedicated to Celestin, and has every other workload using advisory locks been inventoried? `REVOKE ... FROM PUBLIC` affects all users of that database.
- **Lock API:** Will global reader/admin identities be treated as trusted control-plane identities with residual availability risk, be replaced with database-bound scoped identities, or use a redesigned DB-mediated/row-lock transaction? What exact lock ordering and revocation-wins rule is required?
- **Recovery and evidence:** Who approves the pre-change ACL snapshot, operator runbook, live disposable target, incident owner, and final security/release gate? None is established by the source tree.

**Next approval needed:** the database/provider owner must provide authoritative capability evidence for the exact built-in ACL, function ownership, role-grant, and same-transaction operations on the selected Neon configuration. The Celestin security/product owners must separately approve the reader/admin lock-scope design and revocation ordering. Until both are recorded, do not create or apply `0010`, enable hosted mode, or mark tenant isolation ready.
