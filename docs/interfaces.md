# Retrieval Interfaces

## Confirmed boundaries

- Member 1 owns database schemas, connections, repositories, ingestion, and
  decision persistence.
- Member 2 owns retrieval, ranking, context assembly, and the planned embedding
  provider abstraction.
- Member 3 owns the MCP server, public tool definitions, request validation,
  and client integration.
- The current branch contains an isolated Member 2 implementation and synthetic
  tests. It does not contain Member 1's production schema/repositories or
  Member 3's server/tool contract.

## Current Member 2 implementation

| Interface | Current signature / output | Notes |
|---|---|---|
| FTS adapter | `FtsMessageSearch(connection: sqlite3.Connection, schema: FtsSchema).search(query: str, *, project_id: str, limit: int = 10) -> list[SearchResult]` | `FtsSchema` maps an already-existing FTS5 table and columns. Results carry `message_id`, `project_id`, `source_id`, `content`, optional `timestamp`, and `relevance_score`. This direct connection adapter is for isolated work and has not been matched to Member 1's contract. |
| Ranking | `rank_candidates(candidates, *, project_id: str, policy: RankingPolicy = RankingPolicy()) -> list[RetrievalCandidate]` | Rechecks project, filters draft/deprecated decision candidates by the provisional policy, applies decision tier, BM25 score, recency tie-break, then stable IDs. |
| Context | `build_context_bundle(candidates, *, project_id: str, token_budget: int = 2_000, ranking_policy: RankingPolicy = RankingPolicy(), token_counter: TokenCounter | None = None) -> ContextBundle` | Produces traceable JSON Lines, per-record same-project exclusions, and reason counts. Foreign-project exclusions are count-only. The default byte-based count is an estimate, not a model token count. |

These are Member 2 implementation interfaces, not public MCP signatures.
Details and verified behavior are in `docs/retrieval.md`.

## Proposed embedding interface

No `src/memory_bridge/embeddings/` package or provider implementation exists on
this branch. An embedding interface remains proposed for a later phase:

```text
EmbeddingProvider.embed(texts: Sequence[str]) -> Sequence[Sequence[float]]
```

Provider sync/async behavior, dimensions, normalization, batching, errors, and
whether an embedding interface belongs in the first integration remain open.
No network or paid API is needed by the current tests.

## Pending Member 1 decisions

- Actual `chat_messages` and `project_memory` schema fields, keys, source links,
  project isolation fields, timestamps, and status values.
- Repository methods, return types, connection/session ownership, and error
  behavior.
- FTS5 index ownership and how search rows map to source records.
- How canonical decisions are queried/scored alongside message matches.
- Whether approved decision priority, draft inclusion, and deprecated override
  behavior match the provisional Member 2 ranking policy.

## Pending Member 3 decisions

- Public retrieval tool arguments/defaults and whether search and context are
  separate operations.
- Response serialization for records, source IDs, timestamps, scores, context
  budget estimates, and exclusions.
- Public error mapping and whether draft/deprecated overrides are exposed.

No production integration is confirmed until both teammate contracts are
provided and reviewed.
