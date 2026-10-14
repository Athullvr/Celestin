# Evaluation results

```json
{
  "dataset": "dev",
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
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
  "chat_queries": 5,
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
  "timestamp_utc": "2026-10-14T06:08:10Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 0.58 | 0.08 |
| gold-section recall | 0.46 | 0.04 |
| document source correct | 0.83 | 0.75 |
| section source correct | 0.58 | 0.08 |
| MRR of answer item | 0.53 | 0.04 |
| mean context bytes | 1638.92 | 1670.67 |
| median context bytes | 1683.50 | 1734.50 |
| mean items | 1.92 | 2.25 |
| gold section MRR, fused order | 0.74 | 0.74 |
| gold section MRR, after rerank | 0.74 | 0.23 |
| answers per KB of context | 0.36 | 0.05 |
| gold-section recall per KB | 0.28 | 0.02 |
| rerank latency (ms, mean) | 0.00 | 673.13 |
| section candidates after filtering | 18.58 | 18.58 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 563.08 |
| System 1 shortlist inference calls | 0 | 15 |
| System 1 latency per shortlist inference (ms) | 0.00 | 638.16 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 1.75 | 2.08 |
| unrelated item rate | 0.66 | 0.96 |
| answer-bearing share of context | 0.31 | 0.04 |
| queries dropping a record for budget | 12 | 12 |
| mean total latency (ms) | 47.71 | 724.72 |
| mean local latency (ms) | 47.71 | 724.72 |
| chat recall (5 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | J H + local Julia-1 System 1 reranking |
|---|---|---|
| answer text in context | 0.92 | 0.75 |
| gold-section recall | 0.73 | 0.57 |
| document source correct | 1 | 1 |
| section source correct | 0.92 | 0.75 |
| MRR of answer item | 0.73 | 0.22 |
| mean context bytes | 17743.50 | 17882.42 |
| median context bytes | 19562.00 | 19583.00 |
| mean items | 12.58 | 12.33 |
| gold section MRR, fused order | 0.74 | 0.74 |
| gold section MRR, after rerank | 0.74 | 0.23 |
| answers per KB of context | 0.05 | 0.04 |
| gold-section recall per KB | 0.04 | 0.03 |
| rerank latency (ms, mean) | 0.00 | 636.17 |
| section candidates after filtering | 18.58 | 18.58 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 536.44 |
| System 1 shortlist inference calls | 0 | 15 |
| System 1 latency per shortlist inference (ms) | 0.00 | 607.97 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| sections in final context | 12.42 | 12.17 |
| unrelated item rate | 0.90 | 0.91 |
| answer-bearing share of context | 0.10 | 0.11 |
| queries dropping a record for budget | 10 | 10 |
| mean total latency (ms) | 55.34 | 692.78 |
| mean local latency (ms) | 55.34 | 692.78 |
| chat recall (5 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- J H + local Julia-1 System 1 reranking: budget 2000: lost 7, gained 1 (lost: how big is the default embedding model download, why was sqlite-vec chosen over the alternatives, how are keyword and vector result lists combined, which command registers the server with the coding agent, which ChatGPT plans can use write capable connectors, what stays unchanged when semantic search is switched off, how does the vector index recover after an interrupted run); budget 20000: lost 2, gained 0 (lost: why was sqlite-vec chosen over the alternatives, which command registers the server with the coding agent)

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 14.48 s, 66 records
- J H + local Julia-1 System 1 reranking: 13.75 s, 66 records

## System 1 local resource snapshot

- Julia-1 revision `a85b127321d580d65176c89ced8273f305745d85`; checkpoint `df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72`; load 13609.1 ms; warmup 50.2 ms; checkpoint 550.5 MiB; RSS change during load/warmup +995.3 MiB.
