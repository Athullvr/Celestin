# Celestin semantic search: design and operations

## Components

| Component | What it is | Where |
| --- | --- | --- |
| MCP server | FastMCP tools over stdio (`celestin`; aliases `orbit`, `memory-bridge`) | `src/orbit/mcp_server/` |
| Retrieval engine | FTS5 search, optional vector search, RRF fusion, policy ranking, budgeted context | `src/orbit/retrieval/` |
| Semantic layer | Embedding provider, vector index, indexer, `celestin-index` CLI | `src/orbit/semantic/` |
| Plugin package | **None exists in this repository.** There is no plugin manifest, marketplace catalog or skill to rename or wire up. | n/a |

The Python import package is still `orbit` (renaming it would break imports for no user benefit). The distribution is `celestin-memory`.

## Why SQLite stays authoritative

Messages and decisions live only in the SQLite database. The vector index is a *derived* file that stores references (`chat_message` or `canonical_decision` plus the SQLite id), the project, a content hash and the vector, never text. Search results are always re-read from SQLite and re-filtered by project and decision status, so a stale or corrupt index cannot leak content or resurrect a draft.

## FTS5 vs semantic

FTS5 matches the literal terms (AND semantics): ideal for identifiers, error codes and exact names. Embeddings match meaning, so they find reworded memories but are weak on rare tokens. Celestin runs both and fuses them, so neither replaces the other.

## Vector store decision

| Option | Verdict |
| --- | --- |
| **A. sqlite-vec** (chosen) | Single small wheel, no server, loads into the stdlib `sqlite3` (verified on Python 3.12/Linux with SQLite 3.45), supports a partition key (project) and a metadata column (kind) *inside* the KNN query, cosine distance, deletes, and is trivially testable with temp files. Brute-force exact KNN. |
| B. LanceDB | Heavier dependency (Arrow), separate storage format and its own lifecycle, no benefit at this scale. |
| C. Qdrant | A separate service. Contradicts local-first and adds an operational and network surface. Rejected for the MVP. |

sqlite-vec is pre-1.0 (0.1.x), hence the `<0.2` pin. A future hosted deployment would still need its own storage and authentication work; the `SemanticSearch` / `VectorIndex` boundary is where that would be swapped.

The vector data is in its **own file** (not a table in the main database) so existing databases are untouched, clients without the extension can still open the main database, and "delete and rebuild" is always safe.

## Embedding model decision

Default: `BAAI/bge-small-en-v1.5` via `fastembed`: MIT license, 384 dimensions, ONNX Runtime (no PyTorch), about 130 MB download once. Verified here: it loaded, embedded in batches, and the "local persistence / hosted infrastructure" example scored 0.69 versus 0.43 for an unrelated sentence. It is English-focused; change `CELESTIN_EMBEDDING_MODEL` to another model fastembed supports (then run `celestin-index rebuild`).

A remote embedding API was **not** implemented: it would send project data to a third party and needs credentials handling. `EmbeddingProvider` (`embed_documents`, `embed_query`, `model_id`, `dimension`) is the extension point; a remote provider would need explicit opt-in documentation.

The test suite uses a deterministic fake provider (`tests/semantic/fakes.py`). It exists only for unit tests and is not wired into the product.

## Indexing

Embedding input: messages use their content; approved decisions use `key` + newline + `value`. Models truncate long input (512 tokens for the default model), so only the start of very long records influences the vector.

- On `ingest_chat_message`, the message is indexed best-effort after the SQLite commit. A failure is logged and never fails the write.
- `celestin-index sync` scans SQLite in id-ordered batches (never loading the database into memory), embeds records whose (project, content hash) is missing or different, then removes index entries whose source no longer exists or is no longer eligible (deleted, project changed, decision no longer approved). It is idempotent and resumable: after a crash or outage, re-run it.
- No MCP tool approves decisions, so an approved decision becomes searchable after `celestin-index sync`.
- SQLite and the vector file are separate stores. There is no cross-store transaction; reconciliation by `sync` is the recovery mechanism.

## Hybrid retrieval

1. Validate inputs (unchanged MCP boundary).
2. FTS5 search (messages and decisions) as before.
3. Embed the query; run project- and kind-filtered KNN; drop hits below the cosine cut-off.
4. Reload every vector hit from SQLite with a project filter (hits with no row are dropped and reported); decisions take their status from SQLite.
5. Reciprocal Rank Fusion per record kind: `score = Σ 1/(60 + rank)`. A record in both lists is counted once with both contributions. Ties break by ascending id.
6. The fused value `-score` is placed in `relevance_score` (lower is better, like BM25), then the unchanged ranking policy runs (approved decisions first; drafts and deprecated decisions excluded) and the unchanged budget-limited context builder.

## Failure behavior

| Situation | Behavior |
| --- | --- |
| Semantic search disabled | FTS5 only; response schema unchanged. |
| Embedding model missing or fails, `fastembed`/`sqlite-vec` not installed | FTS5-only results, `retrieval.mode = "fts_fallback"` with a warning, log line. Not an error. |
| Vector file missing, wrong model/dimension, inconsistent or corrupt | Same fallback; the warning names `celestin-index sync` or `rebuild`. |
| Vector hit with no matching SQLite row (stale) | Hit ignored; warning in `retrieval.warnings`. |
| Embedding fails while indexing | Write succeeds; `celestin-index sync` reports the error (non-zero exit) and resumes later. |
| FTS5 index missing | Unchanged: `RETRIEVAL_UNAVAILABLE`. |

## Security and isolation

Project filtering happens inside the KNN query and again when SQLite rows are reloaded. The `project` argument is still a caller-chosen scope, not authentication. No network listener is added; the only network use is the one-time model download.

## Rollback

Unset `CELESTIN_SEMANTIC_SEARCH` to return to FTS5-only behavior. The SQLite schema is unchanged by this work, so the old `orbit`/`memory-bridge` commands and `MEMORY_BRIDGE_DB_PATH` keep working. The `*.vectors.db` file can be deleted at any time.
