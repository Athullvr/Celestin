# Evaluation results

```json
{
  "dataset": "heldout",
  "dataset_version": "1",
  "dataset_sha256": "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828",
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
  "chat_queries": 4,
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
  "timestamp_utc": "2026-10-13T06:26:36Z",
  "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 20000

| metric | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.08 | S + rerank (lexical) | S + rerank (cross-encoder) | S + rerank (cross-encoder + RRF) | S + margin 0.08 + rerank (lexical) | S + margin 0.08 + rerank (cross-encoder) | S + margin 0.08 + rerank (cross-encoder + RRF) | S + rerank (cross-encoder) + top-5 | S + rerank (cross-encoder) + top-8 | S + margin 0.08 + rerank (cross-encoder) + top-8 | S + margin 0.08 + rerank (cross-encoder + RRF) + top-8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 1 | 1 | 1 | 0.92 | 1 | 1 | 1 | 1 | 0.92 | 0.92 | 1 | 1 |
| gold-section recall | 1.00 | 1.00 | 1.00 | 0.92 | 1.00 | 1.00 | 1.00 | 1.00 | 0.92 | 0.92 | 1.00 | 1.00 |
| document source correct | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| section source correct | 1 | 1 | 1 | 0.92 | 1 | 1 | 1 | 1 | 0.92 | 0.92 | 1 | 1 |
| MRR of answer item | 0.67 | 0.66 | 0.72 | 0.65 | 0.68 | 0.72 | 0.66 | 0.68 | 0.65 | 0.65 | 0.66 | 0.68 |
| mean context bytes | 17604.08 | 13656.67 | 17636.42 | 17702.83 | 17675.33 | 13717.33 | 13724.92 | 13703.50 | 8603.08 | 12613.25 | 11456.33 | 11014.92 |
| median context bytes | 19750.00 | 12917.50 | 19699.50 | 19871.50 | 19778.50 | 12917.50 | 12917.50 | 12917.50 | 8534.50 | 12795.00 | 11509.00 | 10588.00 |
| mean items | 12.08 | 8.92 | 11.75 | 11.25 | 11.33 | 8.83 | 8.67 | 8.75 | 4.92 | 7.42 | 6.75 | 6.75 |
| gold section MRR, fused order | 0.67 | 0.66 | 0.67 | 0.67 | 0.67 | 0.66 | 0.66 | 0.66 | 0.67 | 0.67 | 0.66 | 0.66 |
| gold section MRR, after rerank | 0.67 | 0.66 | 0.72 | 0.66 | 0.68 | 0.72 | 0.66 | 0.68 | 0.66 | 0.66 | 0.66 | 0.68 |
| answers per KB of context | 0.06 | 0.07 | 0.06 | 0.05 | 0.06 | 0.07 | 0.07 | 0.07 | 0.11 | 0.07 | 0.09 | 0.09 |
| gold-section recall per KB | 0.06 | 0.07 | 0.06 | 0.05 | 0.06 | 0.07 | 0.07 | 0.07 | 0.11 | 0.07 | 0.09 | 0.09 |
| rerank latency (ms, mean) | 0.00 | 0.00 | 1.94 | 1030.58 | 962.42 | 1.43 | 646.17 | 641.43 | 1194.08 | 991.47 | 658.65 | 637.87 |
| section candidates after filtering | 22.08 | 10.25 | 22.08 | 22.08 | 22.08 | 10.25 | 10.25 | 10.25 | 22.08 | 22.08 | 10.25 | 10.25 |
| sections in final context | 12.08 | 8.92 | 11.75 | 11.25 | 11.33 | 8.83 | 8.67 | 8.75 | 4.92 | 7.42 | 6.75 | 6.75 |
| unrelated item rate | 0.89 | 0.84 | 0.88 | 0.89 | 0.88 | 0.84 | 0.84 | 0.84 | 0.78 | 0.85 | 0.82 | 0.82 |
| answer-bearing share of context | 0.11 | 0.14 | 0.11 | 0.10 | 0.11 | 0.14 | 0.14 | 0.14 | 0.17 | 0.12 | 0.15 | 0.16 |
| queries dropping a record for budget | 9 | 3 | 9 | 9 | 9 | 3 | 3 | 3 | 0 | 0 | 0 | 0 |
| mean total latency (ms) | 14.17 | 9.98 | 14.35 | 1051.64 | 980.22 | 12.07 | 661.10 | 658.19 | 1219.23 | 1006.95 | 674.27 | 652.18 |
| mean local latency (ms) | 14.17 | 9.98 | 14.35 | 1051.64 | 980.22 | 12.07 | 661.10 | 658.19 | 1219.23 | 1006.95 | 674.27 | 652.18 |
| chat recall (4 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean strategies run per query | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Answers lost / gained relative to S (same questions)

- S + section margin 0.08: budget 20000: lost 0, gained 0
- S + rerank (lexical): budget 20000: lost 0, gained 0
- S + rerank (cross-encoder): budget 20000: lost 1, gained 0 (lost: what provenance does a decision keep when it has no source message)
- S + rerank (cross-encoder + RRF): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (lexical): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder + RRF): budget 20000: lost 0, gained 0
- S + rerank (cross-encoder) + top-5: budget 20000: lost 1, gained 0 (lost: what provenance does a decision keep when it has no source message)
- S + rerank (cross-encoder) + top-8: budget 20000: lost 1, gained 0 (lost: what provenance does a decision keep when it has no source message)
- S + margin 0.08 + rerank (cross-encoder) + top-8: budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (cross-encoder + RRF) + top-8: budget 20000: lost 0, gained 0

## Indexing

- S deterministic adaptive selector (product, no PageIndex): 7.34 s, 65 records
- S + section margin 0.08: 6.61 s, 65 records
- S + rerank (lexical): 6.52 s, 65 records
- S + rerank (cross-encoder): 7.24 s, 65 records
- S + rerank (cross-encoder + RRF): 6.85 s, 65 records
- S + margin 0.08 + rerank (lexical): 6.78 s, 65 records
- S + margin 0.08 + rerank (cross-encoder): 6.56 s, 65 records
- S + margin 0.08 + rerank (cross-encoder + RRF): 6.71 s, 65 records
- S + rerank (cross-encoder) + top-5: 7.92 s, 65 records
- S + rerank (cross-encoder) + top-8: 6.44 s, 65 records
- S + margin 0.08 + rerank (cross-encoder) + top-8: 6.45 s, 65 records
- S + margin 0.08 + rerank (cross-encoder + RRF) + top-8: 6.41 s, 65 records
