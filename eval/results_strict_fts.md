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
  "fts_relax": false,
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
  "timestamp_utc": "2026-10-12T17:43:27Z"
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
| document source correct | 0 | 0 | 0.92 | 0.92 | 0.92 | 0.58 | 0.58 | 0.83 | 0.92 |
| section source correct | 0 | 0 | 0.58 | 0.58 | 0.58 | 0.25 | 0.25 | 0.83 | 0.58 |
| MRR of answer item | 0.00 | 0.00 | 0.54 | 0.53 | 0.54 | 0.25 | 0.25 | 0.83 | 0.54 |
| mean context bytes | 0 | 45.83 | 1710.08 | 1697.50 | 1721.25 | 1177.50 | 1224.33 | 1128.67 | 1721.25 |
| median context bytes | 0.00 | 0.00 | 1818.50 | 1788.50 | 1826.00 | 1339.00 | 1339.00 | 1284.50 | 1826.00 |
| mean items | 0 | 0.17 | 1.83 | 1.92 | 1.83 | 1.17 | 1.33 | 0.92 | 1.83 |
| unrelated item rate | 0.00 | 0.17 | 0.65 | 0.66 | 0.65 | 0.71 | 0.71 | 0.00 | 0.65 |
| answer-bearing share of context | 0.00 | 0.00 | 0.33 | 0.31 | 0.31 | 0.18 | 0.18 | 0.65 | 0.31 |
| queries dropping a record for budget | 1 | 11 | 12 | 12 | 12 | 12 | 12 | 7 | 12 |
| mean total latency (ms) | 0.30 | 7.17 | 8.52 | 12.99 | 7.69 | 2.69 | 8.79 | 1.26 | 10.51 |
| mean local latency (ms) | 0.30 | 7.17 | 8.52 | 12.99 | 7.69 | 1.28 | 7.46 | 1.25 | 10.51 |
| chat recall (5 queries) | 0.20 | 1.00 | 1.00 | 1.00 | 0.40 | 0.20 | 1.00 | 0.20 | 0.40 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.41 | 1.33 | 0.01 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.50 | 1.40 | 0.10 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Context budget 20000

| metric | A original: docs as messages, FTS5 | B A + semantic | F sections as messages + semantic (no PageIndex) | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | C diagnostic: stand-in navigator + FTS5 | D diagnostic: stand-in navigator + semantic | E diagnostic: oracle navigator (upper bound) | Sd diagnostic: adaptive selector + stand-in navigator |
|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0 | 0.67 | 0.92 | 0.92 | 0.92 | 0.50 | 0.50 | 1 | 0.92 |
| gold-section recall | 0.00 | 0.53 | 0.72 | 0.72 | 0.72 | 0.42 | 0.42 | 0.97 | 0.72 |
| document source correct | 0 | 0.67 | 1 | 1 | 1 | 0.92 | 0.92 | 1 | 1 |
| section source correct | 0 | 0 | 0.92 | 0.92 | 0.92 | 0.50 | 0.50 | 1 | 0.92 |
| MRR of answer item | 0.00 | 0.58 | 0.69 | 0.68 | 0.69 | 0.36 | 0.36 | 1.00 | 0.69 |
| mean context bytes | 1564.17 | 13198.75 | 17610.50 | 17659.92 | 17675 | 4766.17 | 4813 | 3125.25 | 17675 |
| median context bytes | 0.00 | 13751.00 | 19118.00 | 19694.00 | 19694.00 | 4555.50 | 4555.50 | 2423.00 | 19694.00 |
| mean items | 0.17 | 1.67 | 12.08 | 12.50 | 12.33 | 3 | 3.17 | 1.58 | 12.33 |
| unrelated item rate | 0.08 | 0.57 | 0.91 | 0.91 | 0.91 | 0.83 | 0.83 | 0.00 | 0.91 |
| answer-bearing share of context | 0.00 | 0.35 | 0.09 | 0.09 | 0.09 | 0.15 | 0.15 | 0.84 | 0.09 |
| queries dropping a record for budget | 0 | 6 | 10 | 10 | 10 | 0 | 0 | 0 | 10 |
| mean total latency (ms) | 0.28 | 7.36 | 9.43 | 13.89 | 8.99 | 2.72 | 8.62 | 1.26 | 12.35 |
| mean local latency (ms) | 0.28 | 7.36 | 9.43 | 13.89 | 8.99 | 1.32 | 7.32 | 1.26 | 12.35 |
| chat recall (5 queries) | 0.20 | 1.00 | 1.00 | 1.00 | 0.40 | 0.20 | 1.00 | 0.20 | 0.40 |
| fallback frequency | 0 | 0 | 0 | 0 | 0.08 | 0 | 0 | 0 | 0.08 |
| mean strategies run per query | 1 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 12 | 12 | 12 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| model latency mean (ms, observed) | - | - | - | - | - | 1.40 | 1.30 | 0.01 | - |
| model latency p95 (ms, observed) | - | - | - | - | - | 1.40 | 1.30 | 0.10 | - |
| prompt tokens per call (ESTIMATE, chars/4) | - | - | - | - | - | 0 | 0 | 0 | - |

## Indexing

- A original: docs as messages, FTS5: 0.01 s, 12 records
- B A + semantic: 1.63 s, 12 records
- F sections as messages + semantic (no PageIndex): 6.27 s, 66 records
- H heading sections: FTS5 + semantic (product, no PageIndex): 6.26 s, 66 records
- S deterministic adaptive selector (product, no PageIndex): 6.1 s, 66 records
- C diagnostic: stand-in navigator + FTS5: 0.02 s, 66 records
- D diagnostic: stand-in navigator + semantic: 0.04 s, 66 records
- E diagnostic: oracle navigator (upper bound): 0.02 s, 66 records
- Sd diagnostic: adaptive selector + stand-in navigator: 6.09 s, 66 records
