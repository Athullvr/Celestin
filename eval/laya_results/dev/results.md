# Evaluation results

```json
{
  "dataset": "dev",
  "dataset_version": "1",
  "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
  "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d",
  "git_sha": "05ca122",
  "working_tree_dirty": true,
  "python": "3.14.6",
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
  "measured_repeats": 3,
  "warmup_count": 1,
  "doc_queries": 12,
  "chat_queries": 5,
  "documents": 7,
  "systems_run": [
    "H",
    "L"
  ],
  "comparison_baseline": "H",
  "system1_runtime": {
    "name": "laya-multilingual",
    "repo": "convaiinnovations/laya-multilingual",
    "revision": "1720e3e3357cfe1e281542e223f8273b0890ca34",
    "package_version": "0.4.6",
    "python_version": "3.14.6",
    "torch_version": "2.14.1+cu130",
    "torch_threads": 10,
    "device": "cpu",
    "checkpoint_cached": true,
    "checkpoint_bytes": 643835514,
    "load_ms": 3772.61,
    "warmup_ms": 224.58,
    "rss_before_bytes": 1398538240,
    "rss_after_load_bytes": 3102130176,
    "rss_after_warmup_bytes": 3135012864
  },
  "system1_runtimes": {
    "L": {
      "name": "laya-multilingual",
      "repo": "convaiinnovations/laya-multilingual",
      "revision": "1720e3e3357cfe1e281542e223f8273b0890ca34",
      "package_version": "0.4.6",
      "python_version": "3.14.6",
      "torch_version": "2.14.1+cu130",
      "torch_threads": 10,
      "device": "cpu",
      "checkpoint_cached": true,
      "checkpoint_bytes": 643835514,
      "load_ms": 3772.61,
      "warmup_ms": 224.58,
      "rss_before_bytes": 1398538240,
      "rss_after_load_bytes": 3102130176,
      "rss_after_warmup_bytes": 3135012864,
      "timeout_seconds": 30.0
    }
  },
  "historical_julia_reference": {
    "source": "eval/system1_results/dev/results.json",
    "verified_hashes": true,
    "dataset_sha256": "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95",
    "corpus_sha256": "6b431edd90640546ed1d27618760709a5ed43270a69d1e7d04427a7203b5fd7d",
    "git_sha": "05ca122",
    "python": "3.13.15",
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
    "systems": {
      "H": {
        "label": "H heading sections: FTS5 + semantic (product, no PageIndex)",
        "budgets": {
          "2000": {
            "answer_in_context": 0.5833333333333334,
            "mrr": 0.5277777777777778,
            "mean_total_latency_ms": 47.71341424998354,
            "mean_system1_inference_ms": 0.0,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 0.9166666666666666,
            "mrr": 0.7291666666666666,
            "mean_total_latency_ms": 55.33661083321325,
            "mean_system1_inference_ms": 0.0,
            "system1_inference_failures": 0
          }
        }
      },
      "J": {
        "label": "J H + local Julia-1 System 1 reranking",
        "budgets": {
          "2000": {
            "answer_in_context": 0.08333333333333333,
            "mrr": 0.041666666666666664,
            "mean_total_latency_ms": 724.7225115834226,
            "mean_system1_inference_ms": 638.1573333333333,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 0.75,
            "mrr": 0.2193512506012506,
            "mean_total_latency_ms": 692.7830838333952,
            "mean_system1_inference_ms": 607.9699999999999,
            "system1_inference_failures": 0
          }
        }
      }
    }
  },
  "timestamp_utc": "2026-10-14T14:01:34Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 0.58 | 0.33 |
| gold-section recall | 0.46 | 0.25 |
| document source correct | 0.83 | 0.75 |
| section source correct | 0.58 | 0.33 |
| MRR of answer item | 0.53 | 0.33 |
| mean context bytes | 1638.92 | 1751.75 |
| median context bytes | 1683.50 | 1829.50 |
| mean context token count | 1638.92 | 1751.75 |
| mean items | 1.92 | 2 |
| gold section MRR, fused order | 0.74 | 0.74 |
| gold section MRR, after rerank | 0.74 | 0.55 |
| answers per KB of context | 0.36 | 0.19 |
| gold-section recall per KB | 0.28 | 0.14 |
| rerank latency (ms, mean) | 0.00 | 8681.76 |
| section candidates after filtering | 18.58 | 18.58 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 7331.25 |
| System 1 shortlist inference calls | 0 | 45 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8308.75 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 1.75 | 1.83 |
| unrelated item rate | 0.66 | 0.83 |
| answer-bearing share of context | 0.31 | 0.17 |
| queries dropping a record for budget | 36 | 36 |
| mean total latency (ms) | 13.90 | 8696.89 |
| p50 total latency (ms) | 13.84 | 9561.66 |
| p95 total latency (ms) | 15.11 | 12486.04 |
| p95 total System 1 time per query (ms) | 0 | 12224.57 |
| mean local latency (ms) | 13.90 | 8696.89 |
| chat recall (5 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 0.92 | 0.92 |
| gold-section recall | 0.73 | 0.82 |
| document source correct | 1 | 1 |
| section source correct | 0.92 | 0.92 |
| MRR of answer item | 0.73 | 0.54 |
| mean context bytes | 17743.50 | 18041.25 |
| median context bytes | 19562.00 | 19709.00 |
| mean context token count | 17743.50 | 18041.25 |
| mean items | 12.58 | 12.08 |
| gold section MRR, fused order | 0.74 | 0.74 |
| gold section MRR, after rerank | 0.74 | 0.55 |
| answers per KB of context | 0.05 | 0.05 |
| gold-section recall per KB | 0.04 | 0.05 |
| rerank latency (ms, mean) | 0.00 | 8717.06 |
| section candidates after filtering | 18.58 | 18.58 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 7354.35 |
| System 1 shortlist inference calls | 0 | 45 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8334.93 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 12.42 | 11.92 |
| unrelated item rate | 0.90 | 0.88 |
| answer-bearing share of context | 0.10 | 0.12 |
| queries dropping a record for budget | 30 | 30 |
| mean total latency (ms) | 15.00 | 8733.30 |
| p50 total latency (ms) | 14.76 | 9457.88 |
| p95 total latency (ms) | 17.58 | 12363.05 |
| p95 total System 1 time per query (ms) | 0 | 12254.74 |
| mean local latency (ms) | 15.00 | 8733.30 |
| chat recall (5 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- L H + local Laya System 1 reranking: budget 2000: lost 4, gained 1 (lost: how are keyword and vector result lists combined, what stays unchanged when semantic search is switched off, which ChatGPT plans can use write capable connectors, which command registers the server with the coding agent); budget 20000: lost 0, gained 0

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 5.63 s, 66 records
- L H + local Laya System 1 reranking: 5.64 s, 66 records

## Laya local resource snapshot

- Laya `convaiinnovations/laya-multilingual` revision `1720e3e3357cfe1e281542e223f8273b0890ca34`; package 0.4.6, 2.14.1+cu130, cpu; load 3772.6 ms; warmup 224.6 ms; checkpoint 614.0 MiB; RSS change on load +1624.7 MiB; RSS change on warmup +31.4 MiB.

## Saved Julia-1 reference

The table below is the previously recorded H/J run, not a fresh Julia rerun. Dataset and corpus hashes were checked against this run.

| budget | saved H answer rate | saved J answer rate | saved H MRR | saved J MRR | saved H latency (ms) | saved J latency (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 2000 | 0.583 | 0.083 | 0.528 | 0.042 | 47.7 | 724.7 |
| 20000 | 0.917 | 0.750 | 0.729 | 0.219 | 55.3 | 692.8 |
