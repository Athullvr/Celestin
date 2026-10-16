# Evaluation results

```json
{
  "dataset": "rerank_challenge",
  "dataset_version": "1",
  "dataset_sha256": "dd1bb3174fa4f32e5e7c4f03d131d024a1685b665873482b9cec037da7521fac",
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
  "doc_queries": 6,
  "chat_queries": 3,
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
  "timestamp_utc": "2026-10-14T06:09:36Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 0.33 | 0.17 |
| gold-section recall | 0.33 | 0.17 |
| document source correct | 1 | 0.67 |
| section source correct | 0.33 | 0.17 |
| MRR of answer item | 0.33 | 0.08 |
| mean context bytes | 1802 | 1851.50 |
| median context bytes | 1822.50 | 1889.50 |
| mean items | 2 | 2.33 |
| gold section MRR, fused order | 0.61 | 0.61 |
| gold section MRR, after rerank | 0.61 | 0.12 |
| answers per KB of context | 0.18 | 0.09 |
| gold-section recall per KB | 0.18 | 0.09 |
| rerank latency (ms, mean) | 0.00 | 686.83 |
| section candidates after filtering | 28.33 | 28.33 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 527.89 |
| System 1 shortlist inference calls | 0 | 8 |
| System 1 latency per shortlist inference (ms) | 0.00 | 593.88 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 2 | 2.33 |
| unrelated item rate | 0.83 | 0.92 |
| answer-bearing share of context | 0.18 | 0.09 |
| queries dropping a record for budget | 6 | 6 |
| mean total latency (ms) | 61.78 | 745.41 |
| mean local latency (ms) | 61.78 | 745.41 |
| chat recall (3 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 1 | 0.83 |
| gold-section recall | 1.00 | 0.83 |
| document source correct | 1 | 1 |
| section source correct | 1 | 0.83 |
| MRR of answer item | 0.61 | 0.11 |
| mean context bytes | 19778.33 | 19727.67 |
| median context bytes | 19782.00 | 19761.50 |
| mean items | 13.67 | 13.50 |
| gold section MRR, fused order | 0.61 | 0.61 |
| gold section MRR, after rerank | 0.61 | 0.12 |
| answers per KB of context | 0.05 | 0.04 |
| gold-section recall per KB | 0.05 | 0.04 |
| rerank latency (ms, mean) | 0.00 | 684.94 |
| section candidates after filtering | 28.33 | 28.33 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 528.35 |
| System 1 shortlist inference calls | 0 | 8 |
| System 1 latency per shortlist inference (ms) | 0.00 | 594.40 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 13.67 | 13.50 |
| unrelated item rate | 0.93 | 0.93 |
| answer-bearing share of context | 0.07 | 0.05 |
| queries dropping a record for budget | 6 | 6 |
| mean total latency (ms) | 89.97 | 753.08 |
| mean local latency (ms) | 89.97 | 753.08 |
| chat recall (3 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- J H + local Julia-1 System 1 reranking: budget 2000: lost 2, gained 1 (lost: which role values are valid for ingesting a chat message, why is vector data stored in a separate file); budget 20000: lost 1, gained 0 (lost: what timestamp format does the MCP boundary serialize)

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 13.72 s, 64 records
- J H + local Julia-1 System 1 reranking: 14.2 s, 64 records

## System 1 local resource snapshot

- Julia-1 revision `a85b127321d580d65176c89ced8273f305745d85`; checkpoint `df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72`; load 13609.1 ms; warmup 50.2 ms; checkpoint 550.5 MiB; RSS change during load/warmup +995.3 MiB.
