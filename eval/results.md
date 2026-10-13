# Evaluation results

```json
{
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "git_sha": "353a2ea",
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
  "timestamp_utc": "2026-10-12T17:40:35Z"
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
| unrelated item rate | 0.00 | 0.17 | 0.65 | 0.66 | 0.65 | 0.71 | 0.71 | 0.00 | 0.65 |
| answer-bearing share of context | 0.00 | 0.00 | 0.33 | 0.31 | 0.31 | 0.18 | 0.18 | 0.65 | 0.31 |
| queries dropping a record for budget | 11 | 12 | 12 | 12 | 12 | 12 | 12 | 7 | 12 |
| mean total latency (ms) | 2.57 | 9.78 | 8.22 | 15.12 | 11.23 | 2.91 | 8.89 | 1.40 | 9.81 |
| mean local latency (ms) | 2.57 | 9.78 | 8.22 | 15.12 | 11.23 | 1.60 | 7.49 | 1.40 | 9.81 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.31 | 1.40 | 0.01 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.40 | 1.40 | 0.10 | - |
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
| unrelated item rate | 0.38 | 0.57 | 0.90 | 0.90 | 0.90 | 0.83 | 0.83 | 0.00 | 0.90 |
| answer-bearing share of context | 0.48 | 0.41 | 0.10 | 0.10 | 0.10 | 0.15 | 0.15 | 0.84 | 0.10 |
| queries dropping a record for budget | 4 | 9 | 10 | 10 | 10 | 0 | 0 | 0 | 10 |
| mean total latency (ms) | 2.72 | 10.14 | 9.64 | 16.91 | 11.95 | 2.79 | 8.92 | 1.38 | 12.85 |
| mean local latency (ms) | 2.72 | 10.14 | 9.64 | 16.91 | 11.95 | 1.49 | 7.52 | 1.38 | 12.85 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.30 | 1.40 | 0.01 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.30 | 1.40 | 0.10 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Indexing

- A original: docs as messages, FTS5: 0.01 s, 12 records
- B A + semantic: 1.59 s, 12 records
- F sections as messages + semantic (no PageIndex): 6.35 s, 66 records
- H heading sections: FTS5 + semantic (product, no PageIndex): 6.32 s, 66 records
- S deterministic adaptive selector (product, no PageIndex): 6.4 s, 66 records
- C diagnostic: stand-in navigator + FTS5: 0.02 s, 66 records
- D diagnostic: stand-in navigator + semantic: 0.04 s, 66 records
- E diagnostic: oracle navigator (upper bound): 0.02 s, 66 records
- Sd diagnostic: adaptive selector + stand-in navigator: 6.52 s, 66 records
