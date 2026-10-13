# Evaluation results

```json
{
  "dataset": "heldout",
  "dataset_version": "1",
  "dataset_sha256": "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828",
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
  "chat_queries": 4,
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
  "timestamp_utc": "2026-10-13T05:31:40Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.04 | S + section margin 0.08 | S + section margin 0.12 | S + top-3 sections | S + top-5 sections | S + top-8 sections | S + excerpts (1200 B) | S + margin 0.08 + top-5 | S + margin 0.08 + excerpts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.50 | 0.42 | 0.50 |
| gold-section recall | 0.33 | 0.33 | 0.33 | 0.33 | 0.33 | 0.33 | 0.33 | 0.33 | 0.29 | 0.33 | 0.29 |
| document source correct | 0.83 | 0.75 | 0.58 | 0.67 | 0.75 | 0.58 | 0.67 | 0.75 | 0.75 | 0.67 | 0.75 |
| section source correct | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 | 0.50 | 0.42 | 0.50 |
| MRR of answer item | 0.36 | 0.38 | 0.38 | 0.38 | 0.38 | 0.38 | 0.38 | 0.38 | 0.46 | 0.38 | 0.46 |
| mean context bytes | 1717.83 | 1745.67 | 1553.67 | 1654.33 | 1704.08 | 1368.25 | 1532.67 | 1654 | 1754.67 | 1546.33 | 1656.33 |
| median context bytes | 1731.00 | 1808.00 | 1486.50 | 1731.00 | 1731.00 | 1356.00 | 1501.50 | 1642.00 | 1827.00 | 1610.50 | 1737.00 |
| mean items | 2.42 | 2.17 | 1.67 | 2 | 2.08 | 1.25 | 1.67 | 1.92 | 2.33 | 1.75 | 2.08 |
| section candidates after filtering | 22.08 | 22.08 | 5.08 | 10.25 | 18.50 | 22.08 | 22.08 | 22.08 | 22.08 | 10.25 | 10.25 |
| sections in final context | 2.08 | 2.17 | 1.67 | 2 | 2.08 | 1.25 | 1.67 | 1.92 | 2.33 | 1.75 | 2.08 |
| unrelated item rate | 0.83 | 0.78 | 0.78 | 0.78 | 0.78 | 0.64 | 0.76 | 0.78 | 0.79 | 0.78 | 0.74 |
| answer-bearing share of context | 0.21 | 0.21 | 0.21 | 0.21 | 0.21 | 0.28 | 0.22 | 0.21 | 0.24 | 0.21 | 0.26 |
| queries dropping a record for budget | 12 | 12 | 11 | 12 | 12 | 11 | 12 | 12 | 12 | 12 | 12 |
| mean total latency (ms) | 15.24 | 10.92 | 8.85 | 9.09 | 9.74 | 10.18 | 9.13 | 9.11 | 12.84 | 9.98 | 11.12 |
| mean local latency (ms) | 15.24 | 10.92 | 8.85 | 9.09 | 9.74 | 10.18 | 9.13 | 9.11 | 12.84 | 9.98 | 11.12 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean strategies run per query | 3 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | S deterministic adaptive selector (product, no PageIndex) | S + section margin 0.04 | S + section margin 0.08 | S + section margin 0.12 | S + top-3 sections | S + top-5 sections | S + top-8 sections | S + excerpts (1200 B) | S + margin 0.08 + top-5 | S + margin 0.08 + excerpts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| answer text in context | 1 | 1 | 0.92 | 1 | 1 | 0.83 | 0.92 | 0.92 | 0.92 | 0.92 | 0.92 |
| gold-section recall | 1.00 | 1.00 | 0.88 | 1.00 | 1.00 | 0.79 | 0.88 | 0.92 | 0.75 | 0.88 | 0.75 |
| document source correct | 1 | 1 | 1 | 1 | 1 | 0.92 | 1 | 1 | 1 | 1 | 1 |
| section source correct | 1 | 1 | 0.92 | 1 | 1 | 0.83 | 0.92 | 0.92 | 1 | 0.92 | 1 |
| MRR of answer item | 0.64 | 0.67 | 0.67 | 0.66 | 0.67 | 0.64 | 0.66 | 0.66 | 0.63 | 0.66 | 0.62 |
| mean context bytes | 17606.92 | 17604.08 | 8179.08 | 13656.67 | 16917.17 | 5137.83 | 8093.67 | 11552 | 16420.08 | 7842.33 | 11461.83 |
| median context bytes | 19699.00 | 19750.00 | 7096.50 | 12917.50 | 19646.00 | 5152.00 | 8194.00 | 12107.00 | 19708.00 | 7981.00 | 9064.50 |
| mean items | 12.42 | 12.08 | 5.08 | 8.92 | 11.42 | 3 | 4.92 | 7.42 | 14.50 | 4.83 | 9.83 |
| section candidates after filtering | 22.08 | 22.08 | 5.08 | 10.25 | 18.50 | 22.08 | 22.08 | 22.08 | 22.08 | 10.25 | 10.25 |
| sections in final context | 12.08 | 12.08 | 5.08 | 8.92 | 11.42 | 3 | 4.92 | 7.42 | 14.50 | 4.83 | 9.83 |
| unrelated item rate | 0.89 | 0.89 | 0.75 | 0.84 | 0.88 | 0.69 | 0.80 | 0.85 | 0.90 | 0.79 | 0.86 |
| answer-bearing share of context | 0.11 | 0.11 | 0.22 | 0.14 | 0.11 | 0.27 | 0.18 | 0.14 | 0.08 | 0.19 | 0.10 |
| queries dropping a record for budget | 9 | 9 | 0 | 3 | 7 | 0 | 0 | 0 | 8 | 0 | 2 |
| mean total latency (ms) | 16.92 | 13.46 | 9.01 | 9.68 | 11.45 | 9.99 | 9.13 | 9.27 | 14.85 | 10.06 | 11.76 |
| mean local latency (ms) | 16.92 | 13.46 | 9.01 | 9.68 | 11.45 | 9.99 | 9.13 | 9.27 | 14.85 | 10.06 | 11.76 |
| chat recall (5 queries) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fallback frequency | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean strategies run per query | 3 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| navigation calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation failures | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| navigation timeouts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Answers lost / gained relative to S (same questions)

- H heading sections: FTS5 + semantic (product, no PageIndex): budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + section margin 0.04: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: how many results does each keyword search return by default)
- S + section margin 0.08: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + section margin 0.12: budget 2000: lost 0, gained 0; budget 20000: lost 0, gained 0
- S + top-3 sections: budget 2000: lost 0, gained 0; budget 20000: lost 2, gained 0 (lost: how many results does each keyword search return by default, what provenance does a decision keep when it has no source message)
- S + top-5 sections: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: how many results does each keyword search return by default)
- S + top-8 sections: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: how many results does each keyword search return by default)
- S + excerpts (1200 B): budget 2000: lost 1, gained 2 (lost: why does an unknown project look the same as an empty one); budget 20000: lost 1, gained 0 (lost: does the context builder ever clip a record to fit the budget)
- S + margin 0.08 + top-5: budget 2000: lost 0, gained 0; budget 20000: lost 1, gained 0 (lost: how many results does each keyword search return by default)
- S + margin 0.08 + excerpts: budget 2000: lost 1, gained 2 (lost: why does an unknown project look the same as an empty one); budget 20000: lost 1, gained 0 (lost: does the context builder ever clip a record to fit the budget)

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 6.94 s, 65 records
- S deterministic adaptive selector (product, no PageIndex): 6.35 s, 65 records
- S + section margin 0.04: 6.35 s, 65 records
- S + section margin 0.08: 6.27 s, 65 records
- S + section margin 0.12: 6.63 s, 65 records
- S + top-3 sections: 6.54 s, 65 records
- S + top-5 sections: 6.31 s, 65 records
- S + top-8 sections: 6.36 s, 65 records
- S + excerpts (1200 B): 6.61 s, 65 records
- S + margin 0.08 + top-5: 6.64 s, 65 records
- S + margin 0.08 + excerpts: 7.23 s, 65 records
