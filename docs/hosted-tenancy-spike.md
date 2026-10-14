# Hosted tenancy schema spike

**Status:** Review draft for an empty PostgreSQL database. It is not a production migration and is not wired into the SQLite migration runner. The local SQLite schema, MCP tools, package, command aliases, and local authorization remain unchanged.

## Policy defaults

The proposed access rule is **authenticated principal + active workspace + active membership + active explicit project grant**. Workspace roles control administration; they do not grant project data access. `can_write` implies `can_read`. A suspended member or revoked service identity is denied immediately even if its grant row remains. Access checks must occur for every read and write and must use server-resolved project/workspace identifiers, not caller-supplied names as authority.

| Principal | Required for data access | Data permission |
|---|---|---|
| Human member | Authenticated identity; active workspace membership; active explicit project grant | `can_read` for reads; `can_write` for writes. An owner or admin receives no implicit data grant. |
| Invited or suspended human | No eligible active membership | Deny reads and writes, even if a grant row remains. |
| Service identity | Authenticated active identity in the same workspace; active explicit service project grant | Grant controls reads/writes; write implies read. |
| Revoked service identity | No active identity | Deny reads and writes, even if a grant row remains. |
| Local SQLite stdio process | Existing `CELESTIN_LOCAL_PROJECT_ACCESS` process policy, with the Orbit variable as a fallback | Existing behavior only; it does not authenticate or distinguish individual stdio clients. |

Administration policy still needs team approval: who can invite/suspend members, grant/revoke projects, archive/restore resources, transfer ownership, and authorize permanent purge. The selected rule that owners/admins have no implicit project data access is a proposed default for review.

## Entities and relational invariants

The schema includes human users, workspaces, workspace memberships, projects, per-human project grants, service identities and service grants, messages, and canonical project memory. Research/document content remains a separate, optional, rebuildable index until its source of truth is decided.

- Human identity uses `(issuer, subject)`, not email.
- Human project grants require a workspace membership and a project in that same workspace. Workspace/project composite foreign keys reject mismatched grant rows.
- Service identity keys are scoped by `(workspace_id, issuer, subject)`. The chosen identity provider must confirm whether this scope matches its subject guarantees.
- Hosted messages and decisions carry both `workspace_id` and `project_id`; composite project foreign keys reject a mismatched workspace/project pair.
- A decision source reference is `(project_id, source_message_id)`. It must refer to a message in that project. A missing or cross-project source is rejected by the foreign key.
- Duplicate memberships and grants are rejected by primary keys. Database checks enforce valid enum values and `can_write => can_read`.
- Revocation timestamps preserve grant/identity rows for review. Application authorization must require `revoked_at IS NULL`; a valid row is not by itself an access grant.

Constraints validate relational integrity, not caller identity or access. Every hosted request must authenticate its principal and authorize workspace membership, resource lifecycle state, and the applicable explicit grant before invoking storage or retrieval. PostgreSQL row-level security (RLS) is worth evaluating as defense in depth. It is not a substitute for application authorization, and its transaction-local identity context must be correctly isolated when connections are pooled.

## Ownership and lifecycle

`archived_at` makes a workspace, project, message, or decision inactive while retaining its row and provenance. `purge_after` records the earliest proposed purge date; it does not automatically authorize or execute a purge. Normal access and retrieval must exclude an archived workspace/project and archived records. Archiving a workspace blocks access to its descendants; whether it should also archive each project row is still a product decision.

Workspace creation must create an active owner in the same transaction. Ownership transfer first adds the replacement owner, then changes the former owner in one transaction. To prevent concurrent changes from removing the last owner, application logic must lock the workspace row, recheck the active-owner count, and commit the membership change atomically. The current schema has an index for active-owner checks but does not independently enforce this invariant if callers bypass the application transaction.

Foreign keys use restrictive deletion behavior rather than cascading through memory. A workspace/project cannot be hard-deleted while referenced rows remain. An archived source message remains present, so its decision link stays valid. A referenced message cannot be permanently deleted until its referencing decisions are purged or a separately authorized, audited operation detaches their provenance. The retention period, audit record, legal-hold behavior, and purge role/process must be decided before implementing deletion. The `purge_after` checks only require an archive timestamp and a non-earlier eligibility date; they do not verify the caller's purge authority or current time.

## Index review

The draft adds referencing-side indexes that PostgreSQL does not create automatically for foreign keys:

- `celestin_workspace_memberships(user_id)` and a partial active-owner index on `(workspace_id)`.
- `celestin_project_memberships(workspace_id, project_id)` and `(workspace_id, user_id)`.
- `celestin_service_project_grants(workspace_id, project_id)` and `(workspace_id, service_identity_id)`.
- Hosted message retrieval index `(workspace_id, project_id, conversation_id, id)` and project-memory lookup index `(workspace_id, project_id)`.

The project/workspace unique keys and the service-identity `(workspace_id, id)` key cover their workspace-leading lookups. The former standalone `idx_project_memory_project` was redundant with project-leading unique indexes and is removed. Recheck all choices against real authorization and retrieval query plans before production.

## PostgreSQL validation plan

Use only a new, empty, disposable database with a restricted test role and synthetic identifiers/content. Apply the schema, inspect indexes/constraints, then run these cases in isolated transactions or sessions:

| Case | Expected result | Enforced by |
|---|---|---|
| Create a workspace with an active owner, project, same-project message and decision source link | Accepted | FK/unique constraints; the application bootstrap path must always add the owner. |
| Decision points to a source message in a different project or a nonexistent ID | Rejected | Composite message-source FK. |
| Human grant combines a project or membership from another workspace | Rejected | Composite workspace/project and workspace/user FKs. |
| Service grant combines a project and service identity from different workspaces | Rejected | Composite FKs. |
| Duplicate workspace membership, human project grant, or service grant | Rejected | Primary keys. |
| Grant has `can_write=true, can_read=false` | Rejected | `CHECK` constraint. |
| Existing member becomes suspended but grant remains; service identity becomes revoked but grant remains | Data query/write denied; grant rows may remain | Application authorization; add RLS tests if RLS is adopted. The relational schema alone permits retained grants. |
| Create workspace without owner; demote/suspend/remove last active owner; concurrent owner transfers | Application path rejects; concurrent changes leave at least one owner | Transactional application logic with workspace-row locking. Current DDL alone permits ownerless workspaces. |
| Archive workspace/project/record and query normally | Row retained; default data access excludes it | Database timestamp/check constraints plus application authorization/query filters. |
| Set `purge_after` before `archived_at`, or set it while unarchived | Rejected | `CHECK` constraint. |
| Purge before retention date or without purge authority | Denied; DDL alone cannot guarantee this | Restricted purge application/role. Referential deletes remain blocked where children or source links exist. |
| Abort transaction after a multi-row write | No partial rows remain | PostgreSQL transaction semantics; application must use one transaction boundary. |
| Two sessions insert the same membership/grant concurrently | One succeeds; the conflicting insert fails | Primary key/unique constraint. |
| Read/write/search/context request from workspace A names project B | Denied; no records or indexes from B returned/changed | Application authorization and project-scoped repository/retrieval queries; RLS defense-in-depth tests if enabled. |
| Inspect `pg_indexes` for every referencing FK column pair | Expected supporting indexes are present | Catalog inspection plus query-plan review. |

Suggested synthetic source-reference probe after loading a fixture with message ID `501` in project A and project B in the same disposable test database:

```sql
-- Same-project reference should succeed.
INSERT INTO project_memory
    (workspace_id, project_id, key, value, status, source_message_id, created_at, updated_at)
VALUES
    ('00000000-0000-0000-0000-000000000001',
     '20000000-0000-0000-0000-000000000001', 'decision-a', 'synthetic', 'draft', 501, now(), now());

-- Cross-project reference should fail with a foreign-key violation.
INSERT INTO project_memory
    (workspace_id, project_id, key, value, status, source_message_id, created_at, updated_at)
VALUES
    ('00000000-0000-0000-0000-000000000002',
     '20000000-0000-0000-0000-000000000002', 'decision-b', 'synthetic', 'draft', 501, now(), now());
```

Use distinct keys/IDs and roll back the fixture transaction after assertions. Negative statements that abort a transaction must run in separate transactions or sessions. The current draft contains no owner trigger, RLS policies, auth service, or purge service, so those behaviors must be exercised through the application once implemented.

## Validation setup and exact commands

At the last environment check, the Windows PostgreSQL service and client binaries reported version 18.4, and `pg_isready -h 127.0.0.1 -p 5432` accepted connections. Authentication as the current user failed because no password was supplied; no `PGPASSWORD`, `PGUSER`, or `PGPASSFILE` was configured and no `%APPDATA%\postgresql\pgpass.conf` was present. No disposable database credentials were available and this schema has not been executed.

Minimum administrator action: create a new restricted login role and a new empty database owned by that role. Set its password with `psql`'s interactive `\password` command; do not put the password in shell history, repository files, or logs. Confirm the database is disposable before applying this draft.

From the repository root, after those credentials and database are authorized:

```powershell
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '5432'
$env:PGUSER = 'celestin_schema_test'
$env:PGDATABASE = 'celestin_schema_test'

& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
  -X -W -v ON_ERROR_STOP=1 `
  -f 'docs\hosted-tenancy-schema.sql'

& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
  -X -W -v ON_ERROR_STOP=1 -d 'celestin_schema_test' -c '\dt'

& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
  -X -W -v ON_ERROR_STOP=1 -d 'celestin_schema_test' `
  -c "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() ORDER BY tablename, indexname;"
```

`-W` prompts for the password instead of placing it in a command or environment variable. These commands are examples for a confirmed disposable database; they have not been run.

## SQLite compatibility and migration outline

Local SQLite remains supported as-is. Keep the `orbit` package, `orbit` and `memory-bridge` commands, MCP tool contracts, current authorization policy, `CELESTIN_DB_PATH` precedence, and legacy `MEMORY_BRIDGE_DB_PATH`. Do not require PostgreSQL dependencies for local mode.

For a later hosted implementation, add a versioned PostgreSQL repository behind the existing service boundary and select it explicitly. Provision identities and manually approved workspace/project mappings first; migrate workspace/project rows before messages and decisions; validate counts, timestamps, statuses, and source links; rebuild derived FTS/vector/document indexes from authoritative records. Keep SQLite backed up and read-only through cutover. Define rollback before enabling hosted writes; avoid unmanaged dual writes.

## Remaining decisions and risks

1. Confirm workspace administration authority and whether owner/admin roles should ever imply project-data grants (the proposed default is no).
2. Set retention duration, legal holds, restore window, purge authorization/audit, and provenance handling for a permanently purged source message.
3. Decide whether workspace archive updates child project archive timestamps or only blocks access through the parent.
4. Confirm service-identity issuer/subject scope and whether revoked identities can ever be reactivated.
5. Select identity provider, remote transport, and whether/when to add RLS. Do not expose an unauthenticated remote endpoint.
6. Choose the research/document source of truth and migration plan for its separate PageIndex sidecar.
7. Exercise the draft on the authorized disposable PostgreSQL database before considering it a migration.

The next implementation should be an isolated synthetic-data PostgreSQL validation harness after the team approves this schema and policy draft. It must verify relational constraints, owner-transfer concurrency, retention filters, and cross-workspace denial without touching local SQLite data.
