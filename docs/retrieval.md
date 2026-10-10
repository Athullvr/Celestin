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
- Query text is treated as plain Unicode word terms joined with `AND`.
  Punctuation is discarded; FTS operators, prefixes, and phrase syntax are not
  exposed. Empty and punctuation-only queries return an empty list.
- A missing or incompatible configured FTS table raises
  `SearchIndexUnavailable`. Invalid Python input raises `TypeError` or
  `ValueError` as appropriate. Other SQLite operational errors propagate.
- This first version searches messages only. Canonical decisions, status
  filtering, cross-source ranking, token budgets, embeddings, and repository
  integration remain later phases.

## Pending integration contract

Member 1 must provide the real message schema, FTS table/index lifecycle, and
repository/connection access method. This implementation currently accepts a
`sqlite3.Connection` directly for isolated tests; it does not claim that this
is Member 1's production repository API. Member 3's MCP request and response
contract also remains pending.
