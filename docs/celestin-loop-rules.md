# Celestin-specific engineering rules

These rules extend the [reusable Loop Engineering core](loop-engineering-core.md)
for this project. They describe constraints and required checks; they do not
claim that hosted storage, authentication, or authorization has been
implemented. Root `AGENTS.md`, existing contracts, and the active user request
remain authoritative.

## Compatibility and local mode

- Preserve the `orbit` Python package and import compatibility, the `orbit` and
  `memory-bridge` commands, all four public MCP tool names and their contracts,
  and existing local authorization behavior unless an approved migration says
  otherwise.
- Preserve database path precedence: `CELESTIN_DB_PATH` takes precedence over
  `MEMORY_BRIDGE_DB_PATH`; retain the legacy variable when the new variable is
  unset.
- Keep SQLite as the supported local source of truth. Hosted PostgreSQL work
  must not silently change SQLite startup, migrations, paths, or data.
- Use [the MCP interface contract](interfaces.md) for tool arguments,
  validation, errors, IDs, and timestamp semantics. Do not change those
  contracts as an incidental storage or retrieval refactor.

## Hosted storage and tenant security

- Apply PostgreSQL migrations only through the explicit, reviewed operator
  workflow. Never migrate automatically on MCP startup or an ordinary request.
  Treat an already-applied migration as immutable; use a forward migration for
  later changes. Follow [the migration guide](postgres-migrations.md).
- Do not treat a caller-supplied project name as identity or authorization.
  Hosted callers must be authenticated and project/workspace access resolved
  server-side before every read and write.
- Scope message/source references, decisions, keyword search, semantic search,
  caches, and context assembly to the authorized workspace and project. Test
  cross-workspace/project denial, suspended membership, and revoked service
  identities at the applicable application boundary.
- Preserve source provenance, stable public IDs, timestamps, transaction
  behavior, and decision upsert/status semantics across storage adapters.
- Database constraints provide relational integrity, not caller
  authentication or complete application authorization. Do not claim the
  hosted policy or last-active-owner rule is enforced unless its application
  behavior and relevant concurrency tests demonstrate it.
- Keep semantic-vector search and PageIndex out of hosted mode until their
  storage lifecycle and tenant isolation are explicitly designed and tested.
  Their optional local behavior must remain optional.
- Do not bypass `ACCESS_DENIED` by trying another project identifier or
  changing identifiers to gain access.

## Validation boundaries

- Test SQLite persistence and retrieval contracts separately from PostgreSQL
  migration-runner behavior, live PostgreSQL schema/adapter behavior, and
  hosted identity/authorization. Passing one category does not verify the
  others.
- Use synthetic data and a confirmed disposable database for live PostgreSQL
  checks. Do not connect to, migrate, or alter a database unless the task
  explicitly authorizes it and the target is positively verified.
- If authentication, a safe database target, or a required interface is
  unavailable, report the evidence and blocker. Do not invent credentials,
  bypass access controls, or claim an unrun check passed.
- Preserve existing teammate changes and inspect untracked files separately
  before any staging decision. Never push without explicit user approval for
  the specific branch and changes.
