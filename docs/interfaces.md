# Memory Bridge Interfaces

> **Team contract for Members 2 & 3.** Everything needed to consume the
> persistence layer is documented here, including argument validation rules,
> return value shapes, and raised errors. Coordinate with Member 1 before
> relying on anything not covered in this file, and before proposing any
> signature change.

## Overview

- SQLite is the **single source of truth** for raw chat history and canonical
  project decisions. Your vector index (Member 2) may cache embeddings, but
  it must **reference `chat_messages.id` / `project_memory.id`** and never
  become the only copy of a decision.
- The schema has two tables:
  - `chat_messages(id, project, conversation_id, role, content, created_at)`
  - `project_memory(id, project, key, value, status, source_message_id, updated_at)`
    with `UNIQUE (project, key)` and an optional FK
    `source_message_id -> chat_messages.id`.
- All timestamps are ISO-8601 UTC strings with a `Z` designator
  (`2026-10-11T12:34:56.789012Z`).
- `role` ∈ {`user`, `assistant`, `system`}
  `status` ∈ {`draft`, `approved`, `deprecated`}
- Project scoping: every read/write is scoped by the `project` argument.
  One project can never read another project's rows.

## Quick start

```python
from memory_bridge.database.engine import connect
from memory_bridge.repositories import (
    ChatMessageRepository,
    DecisionRepository,
)

conn = connect() # default db (data/memory_bridge.db or $MEMORY_BRIDGE_DB_PATH)
messages = ChatMessageRepository(conn)
decisions = DecisionRepository(conn)

msg_id = messages.insert("my-project", "conv-1", "user", "Use bcrypt for passwords")
decisions.save("my-project", "password-hashing", "bcrypt",
               source_message_id=msg_id, status="approved")
```

## Errors

| Error | Raised when | Module |
|---|---|---|
| `ValidationError` | invalid project/key/role/status/content types; or invalid `limit` | `memory_bridge.repositories._validation` |
| `NotFoundError` | unknown message ID, unknown (project, key), or invalid `source_message_id` reference | same |
| `DatabaseError` | connection/SQL/migration failure | `memory_bridge.database.engine` |

`NotFoundError` subclasses `KeyError`; `ValidationError` subclasses `ValueError`.
Both live in `memory_bridge.repositories._validation` and are re-exported from
`memory_bridge.repositories`:

```python
from memory_bridge.repositories import NotFoundError, ValidationError
```

## Chat messages

### `ChatMessageRepository`

| Method | Returns | Raises |
|---|---|---|
| `insert(project, conversation_id, role, content, created_at=None) -> int` | new message id | `ValidationError` |
| `get(message_id) -> dict` | message dict | `NotFoundError` |
| `list_for_conversation(project, conversation_id, limit=None) -> list[dict]` | chronological messages | `ValidationError` |
| `list_for_project(project) -> list[dict]` | all messages, chronological | `ValidationError` |
| `delete(message_id) -> None` | nothing | `NotFoundError` |

### Module-level shortcut

```python
ingest_chat_message(project, conversation_id, role, content, conn=None) -> int
```

- Matches the team contract signature proposed in the plan (`-> int`).
- Creates/uses the default database when `conn` is not given.
- `created_at` is set automatically (UTC ISO-8601) and cannot be passed.

## Canonical decisions

### `DecisionRepository`

| Method | Returns | Raises |
|---|---|---|
| `save(project, key, value, source_message_id=None, status="draft") -> dict` | full stored row | `ValidationError`, `NotFoundError` |
| `update_status(project, key, status) -> dict` | updated row | `ValidationError`, `NotFoundError` |
| `get(project, key) -> dict` | decision dict | `NotFoundError` |
| `list_for_project(project, status=None, include_deprecated=True) -> list[dict]` | newest-first list | `ValidationError` |
| `delete(project, key) -> None` | nothing | `NotFoundError` |

### Module-level shortcut

```python
save_decision(project, key, value, source_message_id=None, status="draft", conn=None) -> dict
```

- Matches the team contract signature proposed in the plan (`-> dict`).
- Creates/uses the default database when `conn` is not given.

### Semantics

- `save` is a **true upsert** on `(project, key)`: same row is updated in
  place (same `id`), `updated_at` refreshed.
- `source_message_id`, when not `None`, **must** reference an existing
  `chat_messages.id`; otherwise `NotFoundError`. Passing a message ID from
  another project's conversation is technically allowed (IDs are global),
  and the FK is validated — so block Member 2/3 from assuming it's project-
  checked. It is a provenance pointer only.
- Setting `status="deprecated"` preserves the row (tombstone) rather than
  deleting it; use `include_deprecated=False` or `status=` filters to hide.
- Deleting a referenced chat message sets `source_message_id` to NULL
  (`ON DELETE SET NULL`); the decision survives with no source pointer.

## Timestamps and IDs

- `created_at` / `updated_at`: server-side UTC ISO-8601 strings; callers
  never supply these.
- IDs: SQLite `INTEGER PRIMARY KEY` autoincrement-ordered, globally unique
  per table. They are stable, so safe as vector-index reference keys and in
  provenance metadata.

## Project scoping guarantees

- Every repository read/write method requiring project scoping takes an
  explicit `project` argument, and every query filters on it.
- `ValidationError` on empty/non-string project. Empty or unknown
  conversations/keys for a valid project yield empty lists or
  `NotFoundError`, never another project's rows.
- `(project, key)` uniqueness is enforced by the schema, so two projects
  can use identical keys without collision.

## For Member 2 (vector index)

- Embed the **value/content** of records you read via the repositories; use
  the returned `id` (or `source_message_id`) as the vector payload/reference,
  not as a storage layer.
- Re-read from SQLite on startup to rebuild, since SQLite is authoritative
  and the vector index is a cache.
- `list_for_project(..., include_deprecated=False)` is the intended source
  when assembling memory context to avoid surfacing deprecated decisions.

## For Member 3 (MCP tools)

- Wire MCP tool handlers to the repository methods directly (or the two
  contract functions). Wrap `ValidationError`/`NotFoundError` into MCP tool
  error responses using the error table above.
- Treat `save_decision`/`update_status` as the only ways to mutate
  decisions so that status transitions remain validated.
- Recommended tool mapping:
  - save message -> `ingest_chat_message` / `ChatMessageRepository.insert`
  - save decision -> `save_decision` / `DecisionRepository.save`
  - update decision status -> `DecisionRepository.update_status`
  - recall/search -> read via `list_for_project` / `list_for_conversation`,
    ranked in Member 2's index.

## Configuration

| Env var | Purpose |
|---|---|
| `MEMORY_BRIDGE_DB_PATH` | overrides default database location (default: `data/memory_bridge.db`, created on demand) |

## Versioning / migrations

- Schema version tracked with `PRAGMA user_version`; migrations in
  `src/memory_bridge/database/engine.py` (`SCHEMA_MIGRATIONS`).
- A clean checkout self-initializes on first connect. Restart-safe.
- Schema-change coordination: Member 1 owns the schema; Members 2/3 must not
  alter tables directly.
