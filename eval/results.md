# Evaluation results

```json
{
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "git_sha": "e5e8a07",
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
  "timestamp_utc": "2026-10-12T17:32:12Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

**System N skipped:** no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini

**System SN skipped:** no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini

## Context budget 2000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) | Sd diagnostic: adaptive selector + stand-in navigator |
|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0 | 0 | 0.58 | 0.58 | 0.50 | 0.25 | 0.25 | 0.83 | 0.50 |
| gold-section recall | 0.00 | 0.00 | 0.46 | 0.46 | 0.42 | 0.21 | 0.21 | 0.60 | 0.42 |
| document source correct | 0 | 0 | 0.83 | 0.83 | 0.75 | 0.58 | 0.58 | 0.83 | 0.75 |
| section source correct | 0 | 0 | 0.58 | 0.58 | 0.50 | 0.25 | 0.25 | 0.83 | 0.50 |
| MRR of answer item | 0.00 | 0.00 | 0.53 | 0.53 | 0.50 | 0.25 | 0.25 | 0.83 | 0.50 |
| mean context bytes | 0 | 45.83 | 1650.75 | 1638.92 | 1533.33 | 1177.50 | 1224.33 | 1128.67 | 1533.33 |
| median context bytes | 0.00 | 0.00 | 1707.00 | 1683.50 | 1623.00 | 1339.00 | 1339.00 | 1284.50 | 1623.00 |
| mean items | 0 | 0.17 | 1.83 | 1.92 | 1.67 | 1.17 | 1.33 | 0.92 | 1.67 |
| unrelated item rate | 0.00 | 0.17 | 0.65 | 0.66 | 0.68 | 0.71 | 0.71 | 0.00 | 0.68 |
| answer-bearing share of context | 0.00 | 0.00 | 0.33 | 0.31 | 0.30 | 0.18 | 0.18 | 0.65 | 0.30 |
| queries dropping a record for budget | 11 | 12 | 12 | 12 | 11 | 12 | 12 | 7 | 11 |
| mean total latency (ms) | 3.59 | 8.73 | 8.23 | 14.04 | 13.07 | 2.95 | 8.87 | 1.19 | 13.70 |
| mean local latency (ms) | 3.59 | 8.73 | 8.23 | 14.04 | 13.07 | 1.56 | 7.47 | 1.19 | 13.70 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.92 | 0 | 0 | 0 | 0.92 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2.83 | 2 | 3 | 2 | 2.83 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.39 | 1.40 | 0.00 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.50 | 1.40 | 0.00 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Context budget 20000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) | Sd diagnostic: adaptive selector + stand-in navigator |
|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.67 | 0.75 | 0.92 | 0.92 | 0.83 | 0.50 | 0.50 | 1 | 0.83 |
| gold-section recall | 0.62 | 0.66 | 0.73 | 0.73 | 0.69 | 0.42 | 0.42 | 0.97 | 0.69 |
| document source correct | 0.67 | 0.75 | 1 | 1 | 0.92 | 0.92 | 0.92 | 1 | 0.92 |
| section source correct | 0 | 0 | 0.92 | 0.92 | 0.83 | 0.50 | 0.50 | 1 | 0.83 |
| MRR of answer item | 0.67 | 0.71 | 0.73 | 0.73 | 0.71 | 0.36 | 0.36 | 1.00 | 0.71 |
| mean context bytes | 14623.83 | 16999.25 | 17782.92 | 17743.50 | 16096.17 | 4766.17 | 4813 | 3125.25 | 16096.17 |
| median context bytes | 18768.00 | 18695.00 | 19342.50 | 19562.00 | 19118.00 | 4555.50 | 4555.50 | 2423.00 | 19118.00 |
| mean items | 1.58 | 2 | 12.25 | 12.58 | 11.17 | 3 | 3.17 | 1.58 | 11.17 |
| unrelated item rate | 0.38 | 0.57 | 0.90 | 0.90 | 0.90 | 0.83 | 0.83 | 0.00 | 0.90 |
| answer-bearing share of context | 0.48 | 0.41 | 0.10 | 0.10 | 0.10 | 0.15 | 0.15 | 0.84 | 0.10 |
| queries dropping a record for budget | 4 | 9 | 10 | 10 | 9 | 0 | 0 | 0 | 9 |
| mean total latency (ms) | 3.24 | 8.99 | 9.68 | 15.67 | 14.37 | 2.86 | 8.95 | 1.16 | 15.07 |
| mean local latency (ms) | 3.24 | 8.99 | 9.68 | 15.67 | 14.37 | 1.46 | 7.55 | 1.16 | 15.07 |
| chat recall (5 queries) | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.92 | 0 | 0 | 0 | 0.92 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2.83 | 2 | 3 | 2 | 2.83 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.40 | 1.40 | 0.00 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.40 | 1.40 | 0.00 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Indexing

- A original: docs as messages, FTS5: 0.01 s, 12 records
- B A + semantic: 1.58 s, 12 records
- F sections as messages + semantic (no PageIndex): 6.55 s, 66 records
- H heading sections: FTS5 + semantic (product, no PageIndex): 6.04 s, 66 records
- S deterministic adaptive selector (product, no PageIndex): 6.22 s, 66 records
- C diagnostic: stand-in navigator + FTS5: 0.02 s, 66 records
- D diagnostic: stand-in navigator + semantic: 0.04 s, 66 records
- E diagnostic: oracle navigator (upper bound): 0.01 s, 66 records
- Sd diagnostic: adaptive selector + stand-in navigator: 5.97 s, 66 records
