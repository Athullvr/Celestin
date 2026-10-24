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
