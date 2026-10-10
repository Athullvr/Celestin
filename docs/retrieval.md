# SQLite FTS5 Retrieval

## Current implementation

`orbit.retrieval.FtsMessageSearch` queries an existing FTS5 message
table and returns `SearchResult` values with message ID, project ID, source ID,
content, optional timestamp, and BM25 relevance score. Lower (typically more
negative) BM25 scores rank ahead of higher scores. Ties use SQLite's parsed
timestamp descending, then message ID and source ID ascending. Missing or
unparseable SQLite timestamps sort after valid timestamps and remain available
as returned values.

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
- For a non-empty query, the adapter checks `sqlite_master` for a virtual table
  declared with FTS5 before searching. Missing tables, ordinary tables, and
  incompatible column declarations raise `SearchIndexUnavailable`. An empty
  or punctuation-only query returns immediately without checking the table.
- Identifiers are validated and quoted. Query text, project ID, and limit are
  SQL parameters. Every search includes a project ID predicate.
- Query text is matched against the configured content column and treated as
  plain Unicode word terms joined with `AND`.
  Punctuation is discarded; FTS operators, prefixes, and phrase syntax are not
  exposed. Empty and punctuation-only queries return an empty list.
- Unicode word matching uses Python's Unicode word-character pattern to prepare
  terms and SQLite FTS5's configured tokenizer to index/match content. Exact
  tokenization behavior can differ across tokenizer options; those options are
  not configured by this adapter.
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
   Known ISO 8601 timestamps rank ahead of missing timestamps; naive ISO
   datetimes are interpreted as UTC. Non-ISO timestamp values are rejected by
   the ranking DTO until Member 1's timestamp representation is known.
5. Draft and deprecated decisions are excluded by default. Explicit
   `include_drafts=True` includes drafts in a separate tier after messages;
   they retain `status="draft"`. Explicit `include_deprecated=True` includes
   deprecated decisions in the last tier.

These rules are a provisional Member 2 adapter policy because Member 1's
schema/repository contract and the project's agreed cross-source priority
rules are not available yet. The ranking layer rechecks project IDs so
cross-project candidates cannot enter the result list.

## Context bundles and token budget

`build_context_bundle` accepts retrieval candidates, re-applies the ranking and
status policy, and defaults to a 2,000-unit budget. Included records are
rendered as one compact JSON object per line. Each line preserves record ID,
project ID, source ID, timestamp, record kind, status, relevance score, and full
content. The budget applies to the complete rendered text, including metadata.

No compatible tokenizer dependency is installed in this workspace. The default
`Utf8ByteTokenEstimator` counts UTF-8 bytes and reports `token_count_is_estimate`
as true; it does not claim an exact model-token count. Byte count is a
conservative upper bound for tokenizers whose tokens each represent one or
more UTF-8 bytes, but different tokenizer families can have different
accounting. A model-specific `TokenCounter` can be injected later without
changing selection logic.

Selection scans candidates in their ranking order. It includes a complete
record only if the full rendered bundle remains within budget; it never clips
content. An oversized candidate is reported with reason `token_budget` and the
scan continues, so a later smaller record may fit. Exact duplicate content
(case-insensitive after whitespace normalization) is included once; later
copies are reported as `duplicate_content`. Empty content is not used as a
deduplication key. Same-project exclusions keep record, project, source,
timestamp, type, and status metadata. Project-mismatched records are never
included in per-record exclusion details; only their count appears in
`excluded_counts`, avoiding cross-project metadata disclosure. Exclusion counts
cover all rejected inputs by reason. Duplicate detection is textual, not
semantic.

The 2,000 default and approved-decision priority are Member 2 adapter defaults.
Member 1's actual row/repository contract and the agreed project-level context
priority remain pending; this builder is not yet wired to production data.

## Pending integration contract

Member 1 must provide the real message schema, FTS table/index lifecycle, and
repository/connection access method. This implementation currently accepts a
`sqlite3.Connection` directly for isolated tests; it does not claim that this
is Member 1's production repository API. Member 3's MCP request and response
contract also remains pending. The approved-decision priority tier, status
mapping, and optional overrides are Member 2 proposals pending agreement. The
model-specific tokenizer is also unknown; token counts remain estimates unless
the caller injects and identifies a compatible `TokenCounter`.

## Tests and dependencies

Run the retrieval suite with:

```sh
python3 -m pytest -q
```

The current test environment uses Python 3.12, pytest 7.4, SQLite with FTS5,
and the Python standard library in production code. This workspace has no
`pyproject.toml`, setup configuration, or dependency declaration. The retrieval
test `conftest.py` adds `src/` to `sys.path`; production code does not import
test helpers. There is no embeddings package/provider implementation yet; that
abstraction remains a later planned phase.
