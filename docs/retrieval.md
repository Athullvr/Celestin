# SQLite FTS5 Retrieval

## Current implementation

`memory_bridge.retrieval.FtsMessageSearch` queries an existing FTS5 message
table and returns `SearchResult` values with message ID, project ID, source ID,
content, timestamp, and BM25 relevance score. Lower (typically more negative)
BM25 scores rank ahead of higher scores. Ties are ordered by timestamp
descending.

The component does not create, migrate, rebuild, or delete database objects.
The test suite creates a temporary FTS5 table using fixture-only columns. This
is an adapter fixture, not a proposed production schema. `FtsSchema` must be
configured with the actual names supplied by Member 1 before integration.

## Requirements and query behavior

- Python's SQLite runtime must be compiled with FTS5 support. The tests exercise
  the actual runtime by creating a temporary virtual table.
- The configured table must be an FTS5 virtual table with indexed message
  content and retrievable message ID, project ID, source ID, and timestamp
  columns. These metadata columns can be unindexed FTS5 columns or available
  columns on the agreed table design.
- Identifiers are validated and quoted. Query text, project ID, and limit are
  SQL parameters. Every search includes a project ID predicate.
- Query text is matched against the configured content column and treated as
  plain Unicode word terms joined with `AND`.
  Punctuation is discarded; FTS operators, prefixes, and phrase syntax are not
  exposed. Empty and punctuation-only queries return an empty list.
- A missing or incompatible configured FTS table raises
  `SearchIndexUnavailable`. Invalid Python input raises `TypeError` or
  `ValueError` as appropriate. Other SQLite operational errors propagate.
- FTS search returns messages only. Candidate ranking and canonical status
  filtering are available as an independent policy layer; loading canonical
  decisions and combining repository results remain pending integration.

## Candidate ranking policy

`rank_candidates` accepts retrieval DTOs and applies project and status filters
before sorting. Its provisional default rules are:

1. Approved canonical decisions precede historical messages. This is a
   decision-priority tier, not a claim that the decision matched the query
   better. Its FTS relevance score remains unchanged.
2. Within a priority tier, lower FTS5 BM25 scores rank first.
3. Recency is a configurable tie-breaker (`recency_tiebreaker=True` by
   default): newer ISO 8601 timestamps precede older ones only when relevance
   scores tie. No arbitrary relevance/recency weights are combined.
4. Record ID and source ID provide deterministic final tie-breaks.
5. Draft and deprecated decisions are excluded by default. Explicit
   `include_drafts=True` includes drafts in a separate tier after messages;
   they retain `status="draft"`. Explicit `include_deprecated=True` includes
   deprecated decisions in the last tier.

These rules are a provisional Member 2 adapter policy because Member 1's
schema/repository contract and the project's agreed cross-source priority
rules are not available yet. The ranking layer rechecks project IDs so
cross-project candidates cannot enter the result list.

## Pending integration contract

Member 1 must provide the real message schema, FTS table/index lifecycle, and
repository/connection access method. This implementation currently accepts a
`sqlite3.Connection` directly for isolated tests; it does not claim that this
is Member 1's production repository API. Member 3's MCP request and response
contract also remains pending.
