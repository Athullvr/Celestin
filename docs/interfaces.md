# Retrieval Interfaces — Draft Contract

**Status:** Proposed for Member 2 review; not approved by Members 1 or 3.

This document records a retrieval-layer proposal only. The workspace currently
contains no project source, database schema, existing tests, or interface
documentation. No production database or MCP interface is defined here.

## Confirmed facts

- Member 1 owns SQLite schema, connections, repositories, message ingestion,
  and decision persistence.
- Member 3 owns the MCP server, public tool definitions, input validation,
  and client integration.
- Member 2 owns search, embeddings, ranking, and context construction.
- The real `chat_messages` and `project_memory` schemas and repository methods
  have not been provided in this workspace.
- Member 3's retrieval-tool arguments and response format have not been
  provided in this workspace.

## Proposed Member 2 boundary

Member 2 should accept repository/provider interfaces through dependency
injection. It should not create or migrate database tables, open a database
connection, define MCP tools, or decide public request validation rules.

All field names below are **proposed retrieval DTO fields**, not claims about
Member 1's schema or Member 3's public tool format. Mapping from real records to
these DTOs must be agreed during integration.

## Proposed interfaces

| Interface | Proposed signature | Output | Errors / notes |
|---|---|---|---|
| Chat history search | `search_chat_history(query: str, *, project_id: str, limit: int = 10, include_deprecated: bool = False) -> list[SearchResult]` | Ordered results containing `record_id`, `project_id`, `source_id`, `created_at`, `text`, `record_kind`, `status`, and `score` | Proposed `ValueError` for invalid query/limit; repository failures should propagate or be translated by an agreed adapter. Search implementation and source-row mapping depend on Member 1's contract. |
| Approved decisions | `list_approved_decisions(*, project_id: str, limit: int = 20) -> list[DecisionResult]` | Decision records with `record_id`, `project_id`, `source_id`, `created_at`, `text`, `status`, and optional `updated_at` | Proposed to return approved decisions only; exact status values and fields require Member 1 confirmation. |
| Context bundle | `build_context_bundle(query: str, *, project_id: str, token_budget: int, limit: int = 10, include_deprecated: bool = False) -> ContextBundle` | `items` with source IDs/timestamps and text; `token_count`, `token_budget`, and optional truncation/omission metadata | Proposed `ValueError` for nonpositive budget or invalid arguments. Token counting policy and public serialization need agreement. |
| Embedding provider | `EmbeddingProvider.embed(texts: Sequence[str]) -> Sequence[Sequence[float]]` | One vector per input text, stable ordering | Provider-specific errors propagate through an adapter; dimensions, normalization, batching, and async behavior remain undecided. |

### Proposed retrieval DTOs

```text
SearchResult:
  record_id: str
  project_id: str
  source_id: str
  created_at: str
  text: str
  record_kind: str       # e.g. chat_message or project_memory; confirm vocabulary
  status: str | null     # actual values and applicability need Member 1 confirmation
  score: float

DecisionResult:
  record_id: str
  project_id: str
  source_id: str
  created_at: str
  text: str
  status: str            # expected approved/draft/deprecated; confirm Member 1 values
  updated_at: str | null

ContextBundle:
  items: list[SearchResult | DecisionResult]
  token_count: int
  token_budget: int
  omitted_record_ids: list[str]   # optional proposal
```

These are design shapes, not stable serialized formats. In particular,
`created_at` string encoding, score semantics, whether chat records have a
status, and how decisions enter context remain open questions.

## Ownership boundaries

| Concern | Owner | Member 2 integration boundary |
|---|---|---|
| SQLite schema, connection lifecycle, repository methods | Member 1 | Consume agreed repository outputs; do not alter schema or persistence. |
| MCP server, public tool signatures, validation, client integration | Member 3 | Expose retrieval behavior through the agreed tool contract; do not edit server handlers. |
| Ranking, status filtering policy, FTS query composition, context selection, embedding abstraction | Member 2 | Implement after data and public contracts are confirmed. |

## Test design (planned)

These tests are requirements for later phases, not executable acceptance tests
yet. The repository currently has no implementation or test configuration.

| Scenario | Synthetic setup | Expected assertion |
|---|---|---|
| Project isolation | Same query has matching fixture records in two projects | Results contain only the requested project. |
| Source traceability | Matching record has a fixture source ID and timestamp | Both values survive ranking and context assembly unchanged. |
| Status filtering | Approved, draft, and deprecated project memories share terms | Deprecated records are absent by default; draft inclusion policy is explicit; approved decisions receive the agreed priority. |
| Ranking | Records vary in text match, recency, and decision status | Ordering follows documented score/tie-break rules; similarity cannot supersede an approved decision. |
| Context budget | Candidate texts have deterministic fixture token counts | Bundle count does not exceed budget; selection is deterministic and preserves result metadata. |
| Embedding provider | Fake provider returns deterministic vectors | Retrieval handles ordered vectors without network access; provider errors are surfaced predictably. |

## Pending teammate inputs

### Member 1

- Actual `chat_messages` and `project_memory` schemas, including keys, project
  scope, timestamps, source linkage, and status values.
- Repository method names/signatures and returned row/model types, including
  connection/session ownership and error behavior.
- Whether FTS5 objects/indexing are owned by the database layer and how rows
  are linked back to source records.

### Member 3

- Retrieval tool request arguments and defaults, including project identifier,
  result limit, deprecated/draft controls, and context token budget.
- Public response shape, error mapping, and source/timestamp serialization.
- Whether Member 3 expects a single service entry point or separate search and
  context operations.

No integration or public signature is confirmed until those inputs arrive.
