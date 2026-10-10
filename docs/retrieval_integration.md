# Retrieval service integration contract

The retrieval package combines the production SQLite schema with Member 2's
FTS search, ranking, and context builder. It does not change the MCP server or
its tools; Member 3 can connect the service after this interface is agreed.

## Service boundary

```python
RetrievalService.search_chat_history(
    project: str, query: str, limit: int
) -> list[SearchResult]

RetrievalService.retrieve_context(
    project: str, query: str, token_budget: int
) -> ContextBundle
```

Create the database connection with the production initializer, which applies
schema migrations and FTS index setup, then pass it to the service:

```python
from orbit.database.engine import connect
from orbit.retrieval import RetrievalService

conn = connect()  # or connect("path/to/memory_bridge.db")
retrieval = RetrievalService(conn)
messages = retrieval.search_chat_history("my-project", "SQLite", 10)
bundle = retrieval.retrieve_context("my-project", "SQLite", 2_000)
```

The caller owns and closes `conn`. `SearchResult` carries `message_id`,
`project_id`, `source_id`, `content`, `timestamp`, and `relevance_score`.
`source_id` for a chat result is its `conversation_id`; role is not included.

## Production FTS mapping

Schema migration 2 creates `chat_messages_fts` and `project_memory_fts`,
backfills existing rows, and installs insert/update/delete triggers. SQLite
FTS5 must be enabled. The service uses these `FtsSchema` mappings:

| Field | Messages index | Decisions index |
|---|---|---|
| table | `chat_messages_fts` | `project_memory_fts` |
| message ID field | `message_id` | `decision_id` |
| project field | `project_id` | `project_id` |
| source field | `source_id` (`conversation_id`) | `source_id` (`source_message_id`, or `decision:<id>` when absent) |
| timestamp field | `created_at` | `updated_at` |
| indexed content field | `content` | `value` |

The adapter can query the production database after `connect()`; callers do not
create or manage FTS tables themselves. The migration maintains the indexes
when repository writes insert, update, or delete rows.

## Candidate assembly and ranking

`search_chat_history` queries only the project's messages. `retrieve_context`
searches both FTS indexes with the same query, loads canonical decision rows
from `DecisionRepository` for that project, and maps results to retrieval
candidates. Message scores come from BM25 over message content; decision scores
come from BM25 over decision `value`. Lower BM25 scores rank first within a
priority tier. Candidate IDs are stringified table IDs (`message_id` for chat;
`decision:<id>` for decisions), and project and provenance fields are carried
into the bundle.

The default `RankingPolicy` puts approved decisions before historical messages
and excludes drafts and deprecated decisions. This priority is independent of
the BM25 scores. The service limits each FTS result set to 100 candidates by
default; configure `candidate_limit` on `RetrievalService` to change it.

## Budget and traceability

The service passes the requested `token_budget` to `build_context_bundle`.
Its default `Utf8ByteTokenEstimator` counts UTF-8 bytes and marks
`token_count_is_estimate=True`; it is not an exact model tokenizer. The builder
counts the complete rendered JSON Lines context, never clips a record, and
returns a bundle whose measured count is at most the requested budget. An
oversized record is excluded and later smaller records may still fit.

## Reproducible integration check

`tests/retrieval/test_service_integration.py` uses synthetic rows in a
temporary production-schema database. It checks the service signatures in
practice, FTS index synchronization, project isolation, decision/message
assembly, approved-first ordering, default status filtering, and budget
accounting. Run it with:

```sh
python -m pytest tests/retrieval/test_service_integration.py
```
