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

Workspace creation must create an active owner in the same transaction. Every operation that could remove an active owner from the count (role demotion, suspension, membership removal, or account deactivation) must first lock that workspace row with `SELECT ... FOR UPDATE`, then re-read the membership and active-owner count, reject a result below one, and commit the membership change in that same transaction. Every application path that changes ownership must use this same lock order. A transfer adds or activates the replacement owner before demoting the former owner, under the workspace lock and one transaction. This serializes concurrent ownership changes to the same workspace; the second transaction must evaluate the state after it acquires the lock. The partial active-owner index speeds the count but is not an invariant: neither it nor a `CHECK` constraint can enforce a cross-row minimum. If direct SQL writers must also be protected, a database trigger/constraint mechanism needs a separate design review. The current draft does not enforce the invariant outside the application transaction.

Foreign keys use restrictive deletion behavior rather than cascading through memory. A workspace/project cannot be hard-deleted while referenced rows remain. An archived source message remains present, so its decision link stays valid. A referenced message cannot be permanently deleted until its referencing decisions are purged or a separately authorized, audited operation detaches their provenance. The retention period, audit record, legal-hold behavior, and purge role/process must be decided before implementing deletion. The `purge_after` checks only require an archive timestamp and a non-earlier eligibility date; they do not verify the caller's purge authority or current time.

## Index review

The draft adds referencing-side indexes that PostgreSQL does not create automatically for foreign keys:

- `celestin_workspace_memberships(user_id)` and a partial active-owner index on `(workspace_id)`.
- `celestin_project_memberships(workspace_id, project_id)` and `(workspace_id, user_id)`.
- `celestin_service_project_grants(workspace_id, project_id)` and `(workspace_id, service_identity_id)`.
- Hosted message retrieval index `(workspace_id, project_id, conversation_id, id)` and project-memory lookup index `(workspace_id, project_id)`.
- Project-memory provenance index `(project_id, source_message_id)`, non-partial. The source FK references `chat_messages(project_id, id)`. PostgreSQL does not automatically index the referencing columns, so this index supports provenance queries and avoids scanning all `project_memory` rows when checking a referenced message during restrictive updates/deletes. It is intentionally non-partial so all referencing rows are covered by FK enforcement.

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
| Create workspace without owner; demote/suspend/remove last active owner | Application path rejects; DDL-only probe is accepted by current draft | Application transaction must lock the workspace row, re-read the membership/count, and reject any change leaving fewer than one active owner. Current DDL alone permits ownerless workspaces. |
| Two sessions concurrently demote/suspend/remove different owners when only two active owners remain | At most one removal commits; one active owner remains | Application transaction locks the same workspace row before changing memberships. Test both operations in separate sessions with a barrier so both initially contend; verify the second rechecks after acquiring the lock. A normal index is not sufficient. |
| Concurrent ownership transfers or owner activation/deactivation | Each commits atomically; every committed state retains at least one active owner | Same workspace-row lock and count/recheck protocol. Test competing transfers, transfer racing with suspension/removal, and rollback after a rejected operation. |
| Archive workspace/project/record and query normally | Row retained; default data access excludes it | Database timestamp/check constraints plus application authorization/query filters. |
| Set `purge_after` before `archived_at`, or set it while unarchived | Rejected | `CHECK` constraint. |
| Purge before retention date or without purge authority | Denied; DDL alone cannot guarantee this | Restricted purge application/role. Referential deletes remain blocked where children or source links exist. |
| Abort transaction after a multi-row write | No partial rows remain | PostgreSQL transaction semantics; application must use one transaction boundary. |
| Two sessions insert the same membership/grant concurrently | One succeeds; the conflicting insert fails | Primary key/unique constraint. |
| Read/write/search/context request from workspace A names project B | Denied; no records or indexes from B returned/changed | Application authorization and project-scoped repository/retrieval queries; RLS defense-in-depth tests if enabled. |
| Inspect `pg_indexes` for every referencing FK column pair, including `project_memory(project_id, source_message_id)` | Expected supporting indexes are present | Catalog inspection plus query-plan review. |

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

Use distinct keys/IDs and roll back the fixture transaction after assertions. Each expected constraint failure must be isolated in a savepoint or exception subtransaction. The current draft contains no owner trigger, RLS policies, auth service, or purge service, so those behaviors must be exercised through the application once implemented.

### Application authorization checks required before approval

The hosted application is not implemented by this draft. Before Phase 2B approval, tests must show that every read and write authenticates a principal and resolves authorization server-side before storage/retrieval. Cover unauthenticated and unknown principals; active workspace membership plus explicit project grant; owner/admin without an implicit data grant; suspended membership with a retained grant; revoked service identity with a retained grant; denied reads and writes; altered project arguments and cross-workspace/project attempts; source-message references outside the authorized project; and project scoping across search, embeddings, caches, and context assembly. If RLS is adopted, add tests for transaction-local principal isolation under connection pooling as defense in depth. Local SQLite process-level authorization remains a separate mode and must not be represented as per-user hosted authentication.

## Validation setup and exact commands

The user reports that the draft schema was applied to `celestin_schema_test` and the behavioral validation script passed its assertions against that database. Reported checks include valid same-project provenance, rejection of cross-project/cross-workspace and missing-source references, duplicate membership/grant rejection, restrictive provenance deletion (SQLSTATE `23001`), archive/purge checks, and the DDL-only ownerless-workspace probe. The script ended with `ROLLBACK`, and all reported fixture counts were zero. This is user-reported execution evidence; it was not independently rerun or inspected during this update.

The new non-partial provenance index in this draft was added after that reported schema application. It has not been created or checked in the database. Do not reapply this non-idempotent fresh-database schema to the existing test database. Validate the revised draft in a newly confirmed empty disposable database or review a separately approved additive index migration. Concurrency behavior and hosted application authorization remain untested and are required before Phase 2B approval.

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
7. Validate the revised draft, including the provenance index, on a newly confirmed empty disposable PostgreSQL database; then run the owner-concurrency and hosted authorization tests above before considering it for approval.

The next implementation should be an isolated synthetic-data PostgreSQL validation harness after the team approves this schema and policy draft. It must verify relational constraints, owner-transfer concurrency, retention filters, and cross-workspace denial without touching local SQLite data.
