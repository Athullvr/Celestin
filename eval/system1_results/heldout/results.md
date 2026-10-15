# Evaluation results

```json
{
  "dataset": "heldout",
  "dataset_version": "1",
  "dataset_sha256": "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828",
  "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d",
  "git_sha": "05ca122",
  "working_tree_dirty": true,
  "python": "3.13.15",
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
    "J"
  ],
  "comparison_baseline": "H",
  "system1_runtime": {
    "name": "julia-1",
    "revision": "a85b127321d580d65176c89ced8273f305745d85",
    "weights_sha256": "df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72",
    "source_sha256": "e3ab30c5aa6b8d05e53fc549b30b7d4f6e3aa6dede8fb6dfd701783c8526a8c0",
    "tokenizer_sha256": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",
    "python_version": "3.13.15",
    "torch_version": "2.10.0+cu128",
    "transformers_version": "5.0.0",
    "load_ms": 13609.059968999645,
    "warmup_ms": 50.2419029999146,
    "rss_before_bytes": 567422976,
    "rss_after_bytes": 1611075584,
    "weights_file_bytes": 577189056,
    "torch_threads": 4
  },
  "timestamp_utc": "2026-10-14T06:08:56Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 0.42 | 0.08 |
| gold-section recall | 0.33 | 0.08 |
| document source correct | 0.83 | 0.50 |
| section source correct | 0.42 | 0.08 |
| MRR of answer item | 0.36 | 0.08 |
| mean context bytes | 1717.83 | 1786 |
| median context bytes | 1731.00 | 1801.50 |
| mean items | 2.42 | 2.25 |
| gold section MRR, fused order | 0.67 | 0.67 |
| gold section MRR, after rerank | 0.67 | 0.31 |
| answers per KB of context | 0.24 | 0.05 |
| gold-section recall per KB | 0.19 | 0.05 |
| rerank latency (ms, mean) | 0.00 | 654.39 |
| section candidates after filtering | 22.17 | 22.17 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 490.79 |
| System 1 shortlist inference calls | 0 | 12 |
| System 1 latency per shortlist inference (ms) | 0.00 | 654.39 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 2.08 | 1.92 |
| unrelated item rate | 0.83 | 0.96 |
| answer-bearing share of context | 0.21 | 0.06 |
| queries dropping a record for budget | 12 | 12 |
| mean total latency (ms) | 49.77 | 708.94 |
| mean local latency (ms) | 49.77 | 708.94 |
| chat recall (4 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 1 | 0.83 |
| gold-section recall | 1.00 | 0.79 |
| document source correct | 1 | 1 |
| section source correct | 1 | 0.83 |
| MRR of answer item | 0.64 | 0.30 |
| mean context bytes | 17605.75 | 17658.92 |
| median context bytes | 19699.00 | 19712.50 |
| mean items | 12.42 | 12.42 |
| gold section MRR, fused order | 0.67 | 0.67 |
| gold section MRR, after rerank | 0.67 | 0.31 |
| answers per KB of context | 0.06 | 0.05 |
| gold-section recall per KB | 0.06 | 0.04 |
| rerank latency (ms, mean) | 0.00 | 629.16 |
| section candidates after filtering | 22.17 | 22.17 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 471.87 |
| System 1 shortlist inference calls | 0 | 12 |
| System 1 latency per shortlist inference (ms) | 0.00 | 629.17 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 12.08 | 12.08 |
| unrelated item rate | 0.89 | 0.91 |
| answer-bearing share of context | 0.11 | 0.09 |
| queries dropping a record for budget | 9 | 9 |
| mean total latency (ms) | 57.94 | 690.63 |
| mean local latency (ms) | 57.94 | 690.63 |
| chat recall (4 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- J H + local Julia-1 System 1 reranking: budget 2000: lost 4, gained 0 (lost: which table backs the message index in production, which sqlite feature has to be enabled for the service, what python version does the project require, why does an unknown project look the same as an empty one); budget 20000: lost 2, gained 0 (lost: how many results does each keyword search return by default, what provenance does a decision keep when it has no source message)

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 13.62 s, 65 records
- J H + local Julia-1 System 1 reranking: 13.62 s, 65 records

## System 1 local resource snapshot

- Julia-1 revision `a85b127321d580d65176c89ced8273f305745d85`; checkpoint `df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72`; load 13609.1 ms; warmup 50.2 ms; checkpoint 550.5 MiB; RSS change during load/warmup +995.3 MiB.
