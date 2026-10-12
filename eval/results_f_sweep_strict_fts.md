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
    "F",
    "F@10",
    "F@5",
    "F@3",
    "F~0.12",
    "F~0.08",
    "F~0.04"
  ],
  "timestamp_utc": "2026-10-12T16:37:28Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | F sections as messages + semantic (no PageIndex) | F with candidate_limit=10 | F with candidate_limit=5 | F with candidate_limit=3 | F with relative margin 0.12 | F with relative margin 0.08 | F with relative margin 0.04 |
|---|---|---|---|---|---|---|---|
| answer text in context | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 |
| gold-section recall | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 |
| document source correct | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 | 0.83 |
| section source correct | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 |
| MRR of answer item | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 |
| mean context bytes | 1710.08 | 1647 | 1594.92 | 1508.75 | 1710.08 | 1553.83 | 1317.25 |
| mean items | 1.83 | 1.67 | 1.50 | 1.42 | 1.83 | 1.50 | 1.25 |
| unrelated item rate | 0.65 | 0.64 | 0.64 | 0.62 | 0.65 | 0.57 | 0.46 |
| answer-bearing share of context | 0.33 | 0.34 | 0.34 | 0.36 | 0.33 | 0.38 | 0.41 |
| queries dropping a record for budget | 12 | 12 | 12 | 12 | 12 | 10 | 10 |
| mean total latency (ms) | 8.00 | 7.06 | 6.28 | 6.27 | 8.36 | 6.63 | 6.97 |
| mean local latency (ms) | 8.00 | 7.06 | 6.28 | 6.27 | 8.36 | 6.63 | 6.97 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Context budget 20000

| metric | F sections as messages + semantic (no PageIndex) | F with candidate_limit=10 | F with candidate_limit=5 | F with candidate_limit=3 | F with relative margin 0.12 | F with relative margin 0.08 | F with relative margin 0.04 |
|---|---|---|---|---|---|---|---|
| answer text in context | 0.92 | 0.92 | 0.83 | 0.75 | 0.92 | 0.92 | 0.83 |
| gold-section recall | 0.72 | 0.72 | 0.57 | 0.52 | 0.68 | 0.66 | 0.60 |
| document source correct | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| section source correct | 0.92 | 0.92 | 0.83 | 0.75 | 0.92 | 0.92 | 0.83 |
| MRR of answer item | 0.69 | 0.69 | 0.68 | 0.67 | 0.69 | 0.69 | 0.68 |
| mean context bytes | 17610.50 | 13721.08 | 6551.33 | 3933.67 | 15427.25 | 9832.33 | 4160.08 |
| mean items | 12.08 | 9.25 | 4.75 | 2.92 | 10.83 | 7.25 | 3 |
| unrelated item rate | 0.91 | 0.88 | 0.82 | 0.75 | 0.90 | 0.70 | 0.55 |
| answer-bearing share of context | 0.09 | 0.11 | 0.16 | 0.23 | 0.09 | 0.26 | 0.38 |
| queries dropping a record for budget | 10 | 1 | 0 | 0 | 7 | 3 | 0 |
| mean total latency (ms) | 9.91 | 7.52 | 6.32 | 6.03 | 9.02 | 6.95 | 7.09 |
| mean local latency (ms) | 9.91 | 7.52 | 6.32 | 6.03 | 9.02 | 6.95 | 7.09 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Indexing

- F sections as messages + semantic (no PageIndex): 7.47 s, 66 records
- F with candidate_limit=10: 6.77 s, 66 records
- F with candidate_limit=5: 7.4 s, 66 records
- F with candidate_limit=3: 6.95 s, 66 records
- F with relative margin 0.12: 7.24 s, 66 records
- F with relative margin 0.08: 6.81 s, 66 records
- F with relative margin 0.04: 6.79 s, 66 records
