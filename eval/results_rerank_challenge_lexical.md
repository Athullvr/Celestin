# Evaluation results

```json
{
  "dataset": "rerank_challenge",
  "dataset_version": "1",
  "dataset_sha256": "dd1bb3174fa4f32e5e7c4f03d131d024a1685b665873482b9cec037da7521fac",
  "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d",
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
  "doc_queries": 6,
  "chat_queries": 3,
  "documents": 7,
  "systems_run": [
    "S",
    "S+m08",
    "S+r-lex",
    "S+m08+r-lex"
  ],
  "timestamp_utc": "2026-10-13T06:32:27Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 20000

| metric | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.08 | S + rerank (lexical) | S + margin 0.08 + rerank (lexical) |
|---|---|---|---|---|
| answer text in context | 1 | 1 | 1 | 1 |
| gold-section recall | 1.00 | 1.00 | 1.00 | 1.00 |
| document source correct | 1 | 1 | 1 | 1 |
| section source correct | 1 | 1 | 1 | 1 |
| MRR of answer item | 0.61 | 0.61 | 0.74 | 0.77 |
| mean context bytes | 19778.33 | 15852 | 19803.50 | 16375.33 |
| median context bytes | 19782.00 | 17992.00 | 19885.50 | 19226.50 |
| mean items | 13.67 | 10.83 | 13 | 10.67 |
| gold section MRR, fused order | 0.61 | 0.61 | 0.61 | 0.61 |
| gold section MRR, after rerank | 0.61 | 0.61 | 0.74 | 0.77 |
| answers per KB of context | 0.05 | 0.06 | 0.05 | 0.06 |
| gold-section recall per KB | 0.05 | 0.06 | 0.05 | 0.06 |
| rerank latency (ms, mean) | 0.00 | 0.00 | 3.12 | 1.68 |
| section candidates after filtering | 28.33 | 12.67 | 28.33 | 12.67 |
| sections in final context | 13.67 | 10.83 | 13 | 10.67 |
| unrelated item rate | 0.93 | 0.89 | 0.92 | 0.89 |
| answer-bearing share of context | 0.07 | 0.09 | 0.07 | 0.09 |
| queries dropping a record for budget | 6 | 4 | 6 | 4 |
| mean total latency (ms) | 15.56 | 10.62 | 18.75 | 13.01 |
| mean local latency (ms) | 15.56 | 10.62 | 18.75 | 13.01 |
| chat recall (3 queries) | 0.67 | 0.67 | 0.67 | 0.67 |
| fallback frequency | 0 | 0 | 0 | 0 |
| mean strategies run per query | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 |

## Answers lost / gained relative to S (same questions)

- S + section margin 0.08: budget 20000: lost 0, gained 0
- S + rerank (lexical): budget 20000: lost 0, gained 0
- S + margin 0.08 + rerank (lexical): budget 20000: lost 0, gained 0

## Indexing

- S deterministic adaptive selector (product, no PageIndex): 7.48 s, 64 records
- S + section margin 0.08: 6.33 s, 64 records
- S + rerank (lexical): 6.29 s, 64 records
- S + margin 0.08 + rerank (lexical): 6.65 s, 64 records
