# Evaluation results

```json
{
  "dataset": "dev",
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "git_sha": "a80e7b8",
  "python": "3.12.3",
  "pageindex_version": "0.4.0",
  "navigation_model": null,
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "semantic_min_similarity": 0.6,
  "fts_relax": true,
  "budgets": [
    20000
  ],
  "max_sections_per_navigation": 3,
  "doc_queries": 12,
  "chat_queries": 5,
  "documents": 7,
  "systems_run": [
    "S",
    "S+m08",
    "S+r-lex",
    "S+r-ce",
    "S+r-cerrf",
    "S+m08+r-lex",
    "S+m08+r-ce",
    "S+m08+r-cerrf",
    "S+r-ce+k5",
    "S+r-ce+k8",
    "S+m08+r-ce+k8",
    "S+m08+r-cerrf+k8"
  ],
  "timestamp_utc": "2026-10-13T06:29:27Z",
  "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 20000

| metric | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.08 | S + rerank (lexical) | S + rerank (cross-encoder) | S + rerank (cross-encoder + RRF) | S + margin 0.08 + rerank (lexical) | S + margin 0.08 + rerank (cross-encoder) | S + margin 0.08 + rerank (cross-encoder + RRF) | S + rerank (cross-encoder) + top-5 | S + rerank (cross-encoder) + top-8 | S + margin 0.08 + rerank (cross-encoder) + top-8 | S + margin 0.08 + rerank (cross-encoder + RRF) + top-8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 |
| gold-section recall | 0.73 | 0.73 | 0.82 | 0.83 | 0.83 | 0.78 | 0.78 | 0.78 | 0.82 | 0.83 | 0.78 | 0.78 |
| document source correct | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| section source correct | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 |
| MRR of answer item | 0.74 | 0.74 | 0.63 | 0.81 | 0.81 | 0.64 | 0.81 | 0.81 | 0.81 | 0.81 | 0.81 | 0.81 |
| mean context bytes | 17718.58 | 11448.17 | 17810.42 | 17690.33 | 17798.33 | 11492.67 | 11532.25 | 11501.25 | 8141.42 | 12242 | 9630.50 | 9407.58 |
| median context bytes | 19494.50 | 10503.50 | 19468.00 | 19518.50 | 19565.00 | 10504.00 | 10504.00 | 10504.00 | 8125.50 | 12768.50 | 10355.00 | 9342.50 |
| mean items | 12.42 | 7.92 | 12.50 | 11.83 | 12.17 | 7.83 | 7.58 | 7.75 | 4.83 | 7.58 | 6 | 6 |
| gold section MRR, fused order | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 | 0.74 |
| gold section MRR, after rerank | 0.74 | 0.74 | 0.63 | 0.81 | 0.81 | 0.64 | 0.81 | 0.81 | 0.81 | 0.81 | 0.81 | 0.81 |
| answers per KB of context | 0.05 | 0.08 | 0.05 | 0.05 | 0.05 | 0.08 | 0.08 | 0.08 | 0.11 | 0.07 | 0.10 | 0.10 |
| gold-section recall per KB | 0.04 | 0.06 | 0.05 | 0.05 | 0.05 | 0.07 | 0.07 | 0.07 | 0.10 | 0.07 | 0.08 | 0.08 |
| rerank latency (ms, mean) | 0.00 | 0.00 | 1.92 | 953.16 | 885.00 | 1.05 | 511.43 | 511.23 | 1108.27 | 1162.63 | 567.99 | 520.36 |
| section candidates after filtering | 18.58 | 8.67 | 18.58 | 18.58 | 18.58 | 8.67 | 8.67 | 8.67 | 18.58 | 18.58 | 8.67 | 8.67 |
| sections in final context | 12.42 | 7.92 | 12.50 | 11.83 | 12.17 | 7.83 | 7.58 | 7.75 | 4.83 | 7.58 | 6 | 6 |
| unrelated item rate | 0.90 | 0.77 | 0.88 | 0.87 | 0.88 | 0.76 | 0.76 | 0.76 | 0.72 | 0.81 | 0.73 | 0.73 |
| answer-bearing share of context | 0.10 | 0.19 | 0.12 | 0.13 | 0.13 | 0.21 | 0.21 | 0.21 | 0.26 | 0.18 | 0.22 | 0.23 |
| queries dropping a record for budget | 10 | 3 | 10 | 10 | 10 | 3 | 3 | 3 | 0 | 0 | 0 | 0 |
| mean total latency (ms) | 12.23 | 10.35 | 12.82 | 969.82 | 900.60 | 9.95 | 525.37 | 525.89 | 1130.16 | 1185.98 | 586.60 | 533.50 |
| mean local latency (ms) | 12.23 | 10.35 | 12.82 | 969.82 | 900.60 | 9.95 | 525.37 | 525.89 | 1130.16 | 1185.98 | 586.60 | 533.50 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 |
| mean strategies run per query | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Answers lost / gained relative to S (same questions)

- S + section margin 0.08: budget 20000: lost 0, gained 0
- S + rerank (lexical): budget 20000: lost 0, gained 0
- S + rerank (cross-encoder): budget 20000: lost 0, gained 0
- S + rerank (cross-encoder + RRF): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (lexical): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder + RRF): budget 20000: lost 0, gained 0
- S + rerank (cross-encoder) + top-5: budget 20000: lost 0, gained 0
- S + rerank (cross-encoder) + top-8: budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder) + top-8: budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder + RRF) + top-8: budget 20000: lost 0, gained 0

## Indexing

- S deterministic adaptive selector (product, no PageIndex): 7.03 s, 66 records
- S + section margin 0.08: 6.37 s, 66 records
- S + rerank (lexical): 5.99 s, 66 records
- S + rerank (cross-encoder): 6.11 s, 66 records
- S + rerank (cross-encoder + RRF): 5.92 s, 66 records
- S + margin 0.08 + rerank (lexical): 5.91 s, 66 records
- S + margin 0.08 + rerank (cross-encoder): 6.02 s, 66 records
- S + margin 0.08 + rerank (cross-encoder + RRF): 5.99 s, 66 records
- S + rerank (cross-encoder) + top-5: 6.12 s, 66 records
- S + rerank (cross-encoder) + top-8: 8.42 s, 66 records
- S + margin 0.08 + rerank (cross-encoder) + top-8: 6.75 s, 66 records
- S + margin 0.08 + rerank (cross-encoder + RRF) + top-8: 6.24 s, 66 records
