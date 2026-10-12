# Evaluation results

```json
{
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "git_sha": "ae9cabd",
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
    "C",
    "D",
    "E"
  ],
  "timestamp_utc": "2026-10-12T16:41:13Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

**System N skipped:** no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini

## Context budget 2000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) |
|---|---|---|---|---|---|---|
| answer text in context | 0 | 0 | 0.58 | 0.25 | 0.25 | 0.83 |
| gold-section recall | 0.00 | 0.00 | 0.46 | 0.21 | 0.21 | 0.60 |
| document source correct | 0 | 0 | 0.83 | 0.58 | 0.58 | 0.83 |
| section source correct | 0 | 0 | 0.58 | 0.25 | 0.25 | 0.83 |
| MRR of answer item | 0.00 | 0.00 | 0.53 | 0.25 | 0.25 | 0.83 |
| mean context bytes | 0 | 45.83 | 1650.75 | 1177.50 | 1224.33 | 1128.67 |
| mean items | 0 | 0.17 | 1.83 | 1.17 | 1.33 | 0.92 |
| unrelated item rate | 0.00 | 0.17 | 0.65 | 0.71 | 0.71 | 0.00 |
| answer-bearing share of context | 0.00 | 0.00 | 0.33 | 0.18 | 0.18 | 0.65 |
| queries dropping a record for budget | 11 | 12 | 12 | 12 | 12 | 7 |
| mean total latency (ms) | 2.62 | 10.30 | 8.42 | 2.61 | 8.07 | 1.32 |
| mean local latency (ms) | 2.62 | 10.30 | 8.42 | 1.32 | 6.97 | 1.31 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| navigation calls | 0 | 0 | 0 | 12 | 12 | 12 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | 1.29 | 1.11 | 0.01 |
| model latency p95 (ms, observed) | - | - | - | 1.40 | 1.20 | 0.10 |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | 0 | 0 | 0 |

## Context budget 20000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) |
|---|---|---|---|---|---|---|
| answer text in context | 0.67 | 0.75 | 0.92 | 0.50 | 0.50 | 1 |
| gold-section recall | 0.62 | 0.66 | 0.73 | 0.42 | 0.42 | 0.97 |
| document source correct | 0.67 | 0.75 | 1 | 0.92 | 0.92 | 1 |
| section source correct | 0 | 0 | 0.92 | 0.50 | 0.50 | 1 |
| MRR of answer item | 0.67 | 0.71 | 0.73 | 0.36 | 0.36 | 1.00 |
| mean context bytes | 14623.83 | 16999.25 | 17782.92 | 4766.17 | 4813 | 3125.25 |
| mean items | 1.58 | 2 | 12.25 | 3 | 3.17 | 1.58 |
| unrelated item rate | 0.38 | 0.57 | 0.90 | 0.83 | 0.83 | 0.00 |
| answer-bearing share of context | 0.48 | 0.41 | 0.10 | 0.15 | 0.15 | 0.84 |
| queries dropping a record for budget | 4 | 9 | 10 | 0 | 0 | 0 |
| mean total latency (ms) | 2.72 | 10.19 | 9.89 | 2.76 | 8.72 | 1.34 |
| mean local latency (ms) | 2.72 | 10.19 | 9.89 | 1.43 | 7.44 | 1.33 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| navigation calls | 0 | 0 | 0 | 12 | 12 | 12 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | 1.33 | 1.28 | 0.01 |
| model latency p95 (ms, observed) | - | - | - | 1.50 | 1.90 | 0.10 |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | 0 | 0 | 0 |

## Indexing

- A original: docs as messages, FTS5: 0.01 s, 12 records
- B A + semantic: 1.77 s, 12 records
- F sections as messages + semantic (no PageIndex): 6.94 s, 66 records
- C diagnostic: stand-in navigator + FTS5: 0.01 s, 66 records
- D diagnostic: stand-in navigator + semantic: 0.04 s, 66 records
- E diagnostic: oracle navigator (upper bound): 0.01 s, 66 records
