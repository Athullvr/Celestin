# Evaluation results

```json
{
  "dataset": "rerank_challenge",
  "dataset_version": "1",
  "dataset_sha256": "dd1bb3174fa4f32e5e7c4f03d131d024a1685b665873482b9cec037da7521fac",
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
  "doc_queries": 6,
  "chat_queries": 3,
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
    "load_ms": 3666.92,
    "warmup_ms": 227.06,
    "rss_before_bytes": 1408753664,
    "rss_after_load_bytes": 3115798528,
    "rss_after_warmup_bytes": 3148730368
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
      "load_ms": 3666.92,
      "warmup_ms": 227.06,
      "rss_before_bytes": 1408753664,
      "rss_after_load_bytes": 3115798528,
      "rss_after_warmup_bytes": 3148730368,
      "timeout_seconds": 30.0
    }
  },
  "historical_julia_reference": {
    "source": "eval/system1_results/rerank_challenge/results.json",
    "verified_hashes": true,
    "dataset_sha256": "dd1bb3174fa4f32e5e7c4f03d131d024a1685b665873482b9cec037da7521fac",
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
            "answer_in_context": 0.3333333333333333,
            "mrr": 0.3333333333333333,
            "mean_total_latency_ms": 61.77754449981876,
            "mean_system1_inference_ms": 0.0,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 1,
            "mrr": 0.6083333333333334,
            "mean_total_latency_ms": 89.97346000008595,
            "mean_system1_inference_ms": 0.0,
            "system1_inference_failures": 0
          }
        }
      },
      "J": {
        "label": "J H + local Julia-1 System 1 reranking",
        "budgets": {
          "2000": {
            "answer_in_context": 0.16666666666666666,
            "mrr": 0.08333333333333333,
            "mean_total_latency_ms": 745.4070415001297,
            "mean_system1_inference_ms": 593.87625,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 0.8333333333333334,
            "mrr": 0.1107041107041107,
            "mean_total_latency_ms": 753.0809566668116,
            "mean_system1_inference_ms": 594.39625,
            "system1_inference_failures": 0
          }
        }
      }
    }
  },
  "timestamp_utc": "2026-10-14T14:19:17Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 0.33 | 0.33 |
| gold-section recall | 0.33 | 0.33 |
| document source correct | 1 | 0.83 |
| section source correct | 0.33 | 0.33 |
| MRR of answer item | 0.33 | 0.33 |
| mean context bytes | 1802 | 1890.50 |
| median context bytes | 1822.50 | 1933.00 |
| mean context token count | 1802 | 1890.50 |
| mean items | 2 | 1.83 |
| gold section MRR, fused order | 0.61 | 0.61 |
| gold section MRR, after rerank | 0.61 | 0.53 |
| answers per KB of context | 0.18 | 0.18 |
| gold-section recall per KB | 0.18 | 0.18 |
| rerank latency (ms, mean) | 0.00 | 10219.27 |
| section candidates after filtering | 28.33 | 28.33 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 7928.42 |
| System 1 shortlist inference calls | 0 | 24 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8919.47 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 2 | 1.83 |
| unrelated item rate | 0.83 | 0.83 |
| answer-bearing share of context | 0.18 | 0.21 |
| queries dropping a record for budget | 18 | 18 |
| mean total latency (ms) | 15.39 | 10236.45 |
| p50 total latency (ms) | 15.41 | 10077.98 |
| p95 total latency (ms) | 16.28 | 11255.85 |
| p95 total System 1 time per query (ms) | 0 | 11237.91 |
| mean local latency (ms) | 15.39 | 10236.45 |
| chat recall (3 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 1 | 1 |
| gold-section recall | 1.00 | 1.00 |
| document source correct | 1 | 1 |
| section source correct | 1 | 1 |
| MRR of answer item | 0.61 | 0.53 |
| mean context bytes | 19778.33 | 19891.17 |
| median context bytes | 19782.00 | 19903.00 |
| mean context token count | 19778.33 | 19891.17 |
| mean items | 13.67 | 11.33 |
| gold section MRR, fused order | 0.61 | 0.61 |
| gold section MRR, after rerank | 0.61 | 0.53 |
| answers per KB of context | 0.05 | 0.05 |
| gold-section recall per KB | 0.05 | 0.05 |
| rerank latency (ms, mean) | 0.00 | 10187.69 |
| section candidates after filtering | 28.33 | 28.33 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 7922.58 |
| System 1 shortlist inference calls | 0 | 24 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8912.91 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 13.67 | 11.33 |
| unrelated item rate | 0.93 | 0.91 |
| answer-bearing share of context | 0.07 | 0.07 |
| queries dropping a record for budget | 18 | 18 |
| mean total latency (ms) | 17.59 | 10206.55 |
| p50 total latency (ms) | 17.85 | 10133.65 |
| p95 total latency (ms) | 19.20 | 11405.65 |
| p95 total System 1 time per query (ms) | 0 | 11302.84 |
| mean local latency (ms) | 17.59 | 10206.55 |
| chat recall (3 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- L H + local Laya System 1 reranking: budget 2000: lost 2, gained 2 (lost: which role values are valid for ingesting a chat message, why is vector data stored in a separate file); budget 20000: lost 0, gained 0

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 5.73 s, 64 records
- L H + local Laya System 1 reranking: 5.66 s, 64 records

## Laya local resource snapshot

- Laya `convaiinnovations/laya-multilingual` revision `1720e3e3357cfe1e281542e223f8273b0890ca34`; package 0.4.6, 2.14.1+cu130, cpu; load 3666.9 ms; warmup 227.1 ms; checkpoint 614.0 MiB; RSS change on load +1628.0 MiB; RSS change on warmup +31.4 MiB.

## Saved Julia-1 reference

The table below is the previously recorded H/J run, not a fresh Julia rerun. Dataset and corpus hashes were checked against this run.

| budget | saved H answer rate | saved J answer rate | saved H MRR | saved J MRR | saved H latency (ms) | saved J latency (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 2000 | 0.333 | 0.167 | 0.333 | 0.083 | 61.8 | 745.4 |
| 20000 | 1.000 | 0.833 | 0.608 | 0.111 | 90.0 | 753.1 |
