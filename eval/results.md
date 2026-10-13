# Evaluation results

```json
{
  "dataset": "dev",
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "git_sha": "ed2eec0",
  "python": "3.12.3",
  "pageindex_version": "0.4.0",
  "navigation_model": null,
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "semantic_min_similarity": 0.6,
  "fts_relax": true,
  "budgets": [
    2000,
    20000
  ],
  "max_sections_per_navigation": 3,
  "doc_queries": 12,
  "chat_queries": 5,
  "documents": 7,
  "systems_run": [
    "A",
    "B",
    "F",
    "H",
    "S",
    "C",
    "D",
    "E",
    "Sd"
  ],
  "timestamp_utc": "2026-10-13T05:36:19Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

**System N skipped:** no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini

**System SN skipped:** no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini

## Context budget 2000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) | Sd diagnostic: adaptive selector + stand-in navigator |
|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0 | 0 | 0.58 | 0.58 | 0.58 | 0.25 | 0.25 | 0.83 | 0.58 |
| gold-section recall | 0.00 | 0.00 | 0.46 | 0.46 | 0.46 | 0.21 | 0.21 | 0.60 | 0.46 |
| document source correct | 0 | 0 | 0.83 | 0.83 | 0.83 | 0.58 | 0.58 | 0.83 | 0.83 |
| section source correct | 0 | 0 | 0.58 | 0.58 | 0.58 | 0.25 | 0.25 | 0.83 | 0.58 |
| MRR of answer item | 0.00 | 0.00 | 0.53 | 0.53 | 0.54 | 0.25 | 0.25 | 0.83 | 0.54 |
| mean context bytes | 0 | 45.83 | 1650.75 | 1638.92 | 1662.67 | 1177.50 | 1224.33 | 1128.67 | 1662.67 |
| median context bytes | 0.00 | 0.00 | 1707.00 | 1683.50 | 1815.50 | 1339.00 | 1339.00 | 1284.50 | 1815.50 |
| mean items | 0 | 0.17 | 1.83 | 1.92 | 1.83 | 1.17 | 1.33 | 0.92 | 1.83 |
| section candidates after filtering | 0 | 0 | 0 | 18.58 | 18.58 | 3 | 3 | 1.58 | 18.58 |
| sections in final context | 0 | 0 | 0 | 1.75 | 1.83 | 1.17 | 1.17 | 0.92 | 1.83 |
| unrelated item rate | 0.00 | 0.17 | 0.65 | 0.66 | 0.65 | 0.71 | 0.71 | 0.00 | 0.65 |
| answer-bearing share of context | 0.00 | 0.00 | 0.33 | 0.31 | 0.31 | 0.18 | 0.18 | 0.65 | 0.31 |
| queries dropping a record for budget | 11 | 12 | 12 | 12 | 12 | 12 | 12 | 7 | 12 |
| mean total latency (ms) | 2.94 | 9.76 | 9.00 | 16.79 | 9.83 | 2.46 | 9.48 | 1.37 | 10.75 |
| mean local latency (ms) | 2.94 | 9.76 | 9.00 | 16.79 | 9.83 | 1.44 | 8.07 | 1.37 | 10.75 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.02 | 1.41 | 0.00 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.10 | 1.60 | 0.00 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Context budget 20000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) | Sd diagnostic: adaptive selector + stand-in navigator |
|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.67 | 0.75 | 0.92 | 0.92 | 0.92 | 0.50 | 0.50 | 1 | 0.92 |
| gold-section recall | 0.62 | 0.66 | 0.73 | 0.73 | 0.73 | 0.42 | 0.42 | 0.97 | 0.73 |
| document source correct | 0.67 | 0.75 | 1 | 1 | 1 | 0.92 | 0.92 | 1 | 1 |
| section source correct | 0 | 0 | 0.92 | 0.92 | 0.92 | 0.50 | 0.50 | 1 | 0.92 |
| MRR of answer item | 0.67 | 0.71 | 0.73 | 0.73 | 0.74 | 0.36 | 0.36 | 1.00 | 0.74 |
| mean context bytes | 14623.83 | 16999.25 | 17782.92 | 17743.50 | 17718.58 | 4766.17 | 4813 | 3125.25 | 17718.58 |
| median context bytes | 18768.00 | 18695.00 | 19342.50 | 19562.00 | 19494.50 | 4555.50 | 4555.50 | 2423.00 | 19494.50 |
| mean items | 1.58 | 2 | 12.25 | 12.58 | 12.42 | 3 | 3.17 | 1.58 | 12.42 |
| section candidates after filtering | 0 | 0 | 0 | 18.58 | 18.58 | 3 | 3 | 1.58 | 18.58 |
| sections in final context | 0 | 0 | 0 | 12.42 | 12.42 | 3 | 3 | 1.58 | 12.42 |
| unrelated item rate | 0.38 | 0.57 | 0.90 | 0.90 | 0.90 | 0.83 | 0.83 | 0.00 | 0.90 |
| answer-bearing share of context | 0.48 | 0.41 | 0.10 | 0.10 | 0.10 | 0.15 | 0.15 | 0.84 | 0.10 |
| queries dropping a record for budget | 4 | 9 | 10 | 10 | 10 | 0 | 0 | 0 | 10 |
| mean total latency (ms) | 3.29 | 9.93 | 10.79 | 18.23 | 11.35 | 2.42 | 9.06 | 1.23 | 12.04 |
| mean local latency (ms) | 3.29 | 9.93 | 10.79 | 18.23 | 11.35 | 1.33 | 7.69 | 1.23 | 12.04 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.09 | 1.37 | 0.00 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.20 | 1.70 | 0.00 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Answers lost / gained relative to S (same questions)

- A original: docs as messages, FTS5: budget 2000: lost 7, gained 0 (lost: how big is the default embedding model download, why was sqlite-vec chosen over the alternatives, how are keyword and vector result lists combined, which command registers the server with the coding agent, which ChatGPT plans can use write capable connectors, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run); budget 20000: lost 3, gained 0 (lost: which command registers the server with the coding agent, what is the largest context budget a caller may request, what is the error for a source message from another project)
- B A + semantic: budget 2000: lost 7, gained 0 (lost: how big is the default embedding model download, why was sqlite-vec chosen over the alternatives, how are keyword and vector result lists combined, which command registers the server with the coding agent, which ChatGPT plans can use write capable connectors, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run); budget 20000: lost 2, gained 0 (lost: how big is the default embedding model download, what is the largest context budget a caller may request)
- F sections as messages + semantic (no PageIndex): budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- H heading sections: FTS5 + semantic (product, no PageIndex): budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- C diagnostic: stand-in navigator + FTS5: budget 2000: lost 4, gained 0 (lost: how are keyword and vector result lists combined, which command registers the server with the coding agent, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run); budget 20000: lost 5, gained 0 (lost: what happens when the embedding model cannot be reached, what is the largest context budget a caller may request, what is the error for a source message from another project, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run)
- D diagnostic: stand-in navigator + semantic: budget 2000: lost 4, gained 0 (lost: how are keyword and vector result lists combined, which command registers the server with the coding agent, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run); budget 20000: lost 5, gained 0 (lost: what happens when the embedding model cannot be reached, what is the largest context budget a caller may request, what is the error for a source message from another project, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run)
- E diagnostic: oracle navigator (upper bound): budget 2000: lost 0, gained 3; budget 20000: lost 0, gained 1
- Sd diagnostic: adaptive selector + stand-in navigator: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0

## Indexing

- A original: docs as messages, FTS5: 0.01 s, 12 records
- B A + semantic: 1.88 s, 12 records
- F sections as messages + semantic (no PageIndex): 7.61 s, 66 records
- H heading sections: FTS5 + semantic (product, no PageIndex): 6.54 s, 66 records
- S deterministic adaptive selector (product, no PageIndex): 7.68 s, 66 records
- C diagnostic: stand-in navigator + FTS5: 0.02 s, 66 records
- D diagnostic: stand-in navigator + semantic: 0.04 s, 66 records
- E diagnostic: oracle navigator (upper bound): 0.02 s, 66 records
- Sd diagnostic: adaptive selector + stand-in navigator: 6.62 s, 66 records
