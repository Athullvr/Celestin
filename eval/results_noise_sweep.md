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
    "H",
    "S",
    "S+m04",
    "S+m08",
    "S+m12",
    "S+k3",
    "S+k5",
    "S+k8",
    "S+x1200",
    "S+m08+k5",
    "S+m08+x1200"
  ],
  "timestamp_utc": "2026-10-13T05:28:11Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.04 | S + section margin 0.08 | S + section margin 0.12 | S + top-3 sections | S + top-5 sections | S + top-8 sections | S + excerpts (1200 B) | S + margin 0.08 + top-5 | S + margin 0.08 + excerpts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 |
| gold-section recall | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.46 | 0.43 | 0.46 | 0.43 |
| document source correct | 0.83 | 0.83 | 0.75 | 0.83 | 0.83 | 0.83 | 0.83 | 0.83 | 0.83 | 0.83 | 0.92 |
| section source correct | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 | 0.58 |
| MRR of answer item | 0.53 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.58 | 0.54 | 0.58 |
| mean context bytes | 1638.92 | 1662.67 | 1295.33 | 1489.92 | 1620.25 | 1323.67 | 1570.17 | 1595 | 1761 | 1464.67 | 1535.92 |
| median context bytes | 1683.50 | 1815.50 | 1340.00 | 1364.50 | 1623.00 | 1320.50 | 1469.50 | 1471.50 | 1895.00 | 1364.50 | 1403.50 |
| mean items | 1.92 | 1.83 | 1.33 | 1.50 | 1.75 | 1.25 | 1.58 | 1.67 | 1.75 | 1.42 | 1.42 |
| section candidates after filtering | 18.58 | 18.58 | 3.83 | 8.67 | 14.25 | 18.58 | 18.58 | 18.58 | 18.58 | 8.67 | 8.67 |
| sections in final context | 1.75 | 1.83 | 1.33 | 1.50 | 1.75 | 1.25 | 1.58 | 1.67 | 1.75 | 1.42 | 1.42 |
| unrelated item rate | 0.66 | 0.65 | 0.47 | 0.57 | 0.65 | 0.54 | 0.65 | 0.65 | 0.64 | 0.57 | 0.51 |
| answer-bearing share of context | 0.31 | 0.31 | 0.37 | 0.35 | 0.31 | 0.38 | 0.31 | 0.31 | 0.35 | 0.35 | 0.41 |
| queries dropping a record for budget | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 |
| mean total latency (ms) | 17.56 | 10.68 | 8.79 | 8.80 | 9.60 | 11.05 | 9.77 | 8.71 | 12.31 | 8.38 | 9.12 |
| mean local latency (ms) | 17.56 | 10.68 | 8.79 | 8.80 | 9.60 | 11.05 | 9.77 | 8.71 | 12.31 | 8.38 | 9.12 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 |
| mean strategies run per query | 3 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.04 | S + section margin 0.08 | S + section margin 0.12 | S + top-3 sections | S + top-5 sections | S + top-8 sections | S + excerpts (1200 B) | S + margin 0.08 + top-5 | S + margin 0.08 + excerpts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.92 | 0.92 | 0.83 | 0.92 | 0.92 | 0.83 | 0.83 | 0.92 | 0.92 | 0.83 | 0.92 |
| gold-section recall | 0.73 | 0.73 | 0.68 | 0.73 | 0.73 | 0.68 | 0.68 | 0.73 | 0.73 | 0.68 | 0.72 |
| document source correct | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| section source correct | 0.92 | 0.92 | 0.83 | 0.92 | 0.92 | 0.83 | 0.83 | 0.92 | 0.92 | 0.83 | 0.92 |
| MRR of answer item | 0.73 | 0.74 | 0.72 | 0.74 | 0.74 | 0.72 | 0.72 | 0.74 | 0.74 | 0.72 | 0.74 |
| mean context bytes | 17743.50 | 17718.58 | 6075.75 | 11448.17 | 16193 | 5087.58 | 7142.75 | 10927.58 | 16354.75 | 6405.83 | 9982.92 |
| median context bytes | 19562.00 | 19494.50 | 5505.00 | 10503.50 | 18759.50 | 4576.50 | 7027.00 | 11033.50 | 18075.50 | 6476.00 | 8159.00 |
| mean items | 12.58 | 12.42 | 3.83 | 7.92 | 11.25 | 3.08 | 4.83 | 7.58 | 15 | 4.17 | 8.58 |
| section candidates after filtering | 18.58 | 18.58 | 3.83 | 8.67 | 14.25 | 18.58 | 18.58 | 18.58 | 18.58 | 8.67 | 8.67 |
| sections in final context | 12.42 | 12.42 | 3.83 | 7.92 | 11.25 | 3.08 | 4.83 | 7.58 | 15 | 4.17 | 8.58 |
| unrelated item rate | 0.90 | 0.90 | 0.64 | 0.77 | 0.88 | 0.66 | 0.78 | 0.84 | 0.91 | 0.71 | 0.77 |
| answer-bearing share of context | 0.10 | 0.10 | 0.28 | 0.19 | 0.11 | 0.28 | 0.20 | 0.14 | 0.09 | 0.24 | 0.20 |
| queries dropping a record for budget | 10 | 10 | 0 | 3 | 7 | 0 | 0 | 0 | 6 | 0 | 1 |
| mean total latency (ms) | 19.43 | 12.17 | 8.43 | 9.78 | 10.35 | 10.97 | 9.71 | 9.34 | 13.24 | 8.45 | 9.39 |
| mean local latency (ms) | 19.43 | 12.17 | 8.43 | 9.78 | 10.35 | 10.97 | 9.71 | 9.34 | 13.24 | 8.45 | 9.39 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 |
| mean strategies run per query | 3 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Answers lost / gained relative to S (same questions)

- H heading sections: FTS5 + semantic (product, no PageIndex): budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + section margin 0.04: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: what is the largest context budget a caller may request)
- S + section margin 0.08: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + section margin 0.12: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + top-3 sections: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: what is the largest context budget a caller may request)
- S + top-5 sections: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: what is the largest context budget a caller may request)
- S + top-8 sections: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + excerpts (1200 B): budget 2000: lost 1, gained 1 (lost: what stays unchanged when semantic search is switched off); budget 20000: lost 0, gained 0
- S + margin 0.08 + top-5: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: what is the largest context budget a caller may request)
- S + margin 0.08 + excerpts: budget 2000: lost 1, gained 1 (lost: what stays unchanged when semantic search is switched off); budget 20000: lost 0, gained 0

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 7.31 s, 66 records
- S deterministic adaptive selector (product, no PageIndex): 6.5 s, 66 records
- S + section margin 0.04: 6.26 s, 66 records
- S + section margin 0.08: 7.43 s, 66 records
- S + section margin 0.12: 6.78 s, 66 records
- S + top-3 sections: 6.75 s, 66 records
- S + top-5 sections: 6.82 s, 66 records
- S + top-8 sections: 6.74 s, 66 records
- S + excerpts (1200 B): 7.36 s, 66 records
- S + margin 0.08 + top-5: 6.71 s, 66 records
- S + margin 0.08 + excerpts: 6.45 s, 66 records
