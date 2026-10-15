# Evaluation results

```json
{
  "dataset": "heldout",
  "dataset_version": "1",
  "dataset_sha256": "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828",
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
  "chat_queries": 4,
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
    "load_ms": 4017.76,
    "warmup_ms": 229.48,
    "rss_before_bytes": 1408684032,
    "rss_after_load_bytes": 3119173632,
    "rss_after_warmup_bytes": 3152412672
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
      "load_ms": 4017.76,
      "warmup_ms": 229.48,
      "rss_before_bytes": 1408684032,
      "rss_after_load_bytes": 3119173632,
      "rss_after_warmup_bytes": 3152412672,
      "timeout_seconds": 30.0
    }
  },
  "historical_julia_reference": {
    "source": "eval/system1_results/heldout/results.json",
    "verified_hashes": true,
    "dataset_sha256": "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828",
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
            "answer_in_context": 0.4166666666666667,
            "mrr": 0.3611111111111111,
            "mean_total_latency_ms": 49.77129341667327,
            "mean_system1_inference_ms": 0.0,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 1,
            "mrr": 0.6412037037037037,
            "mean_total_latency_ms": 57.94433041660341,
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
            "mrr": 0.08333333333333333,
            "mean_total_latency_ms": 708.9430906664802,
            "mean_system1_inference_ms": 654.3874999999999,
            "system1_inference_failures": 0
          },
          "20000": {
            "answer_in_context": 0.8333333333333334,
            "mrr": 0.2966931216931217,
            "mean_total_latency_ms": 690.628740166782,
            "mean_system1_inference_ms": 629.1650000000001,
            "system1_inference_failures": 0
          }
        }
      }
    }
  },
  "timestamp_utc": "2026-10-14T14:11:47Z"
}
```

Systems C/D/E are diagnostics, not evidence of LLM performance.

## Context budget 2000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 0.42 | 0.33 |
| gold-section recall | 0.33 | 0.25 |
| document source correct | 0.83 | 0.75 |
| section source correct | 0.42 | 0.33 |
| MRR of answer item | 0.36 | 0.28 |
| mean context bytes | 1717.83 | 1756.67 |
| median context bytes | 1731.00 | 1841.50 |
| mean context token count | 1717.83 | 1756.67 |
| mean items | 2.42 | 2.33 |
| gold section MRR, fused order | 0.67 | 0.67 |
| gold section MRR, after rerank | 0.67 | 0.74 |
| answers per KB of context | 0.24 | 0.19 |
| gold-section recall per KB | 0.19 | 0.14 |
| rerank latency (ms, mean) | 0.00 | 8082.23 |
| section candidates after filtering | 22.08 | 22.08 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 6061.67 |
| System 1 shortlist inference calls | 0 | 36 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8082.23 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 2.08 | 2 |
| unrelated item rate | 0.83 | 0.86 |
| answer-bearing share of context | 0.21 | 0.17 |
| queries dropping a record for budget | 36 | 36 |
| mean total latency (ms) | 15.76 | 8097.84 |
| p50 total latency (ms) | 16.39 | 8311.49 |
| p95 total latency (ms) | 18.39 | 11446.61 |
| p95 total System 1 time per query (ms) | 0 | 11384.32 |
| mean local latency (ms) | 15.76 | 8097.84 |
| chat recall (4 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Context budget 20000

| metric | H heading sections: FTS5 + semantic (product, no PageIndex) | L H + local Laya System 1 reranking |
|---|---|---|
| answer text in context | 1 | 0.92 |
| gold-section recall | 1.00 | 0.92 |
| document source correct | 1 | 1 |
| section source correct | 1 | 0.92 |
| MRR of answer item | 0.64 | 0.71 |
| mean context bytes | 17606.92 | 17587.25 |
| median context bytes | 19699.00 | 19639.50 |
| mean context token count | 17606.92 | 17587.25 |
| mean items | 12.42 | 12 |
| gold section MRR, fused order | 0.67 | 0.67 |
| gold section MRR, after rerank | 0.67 | 0.74 |
| answers per KB of context | 0.06 | 0.05 |
| gold-section recall per KB | 0.06 | 0.05 |
| rerank latency (ms, mean) | 0.00 | 8091.91 |
| section candidates after filtering | 22.08 | 22.08 |
| System 1 rerank latency (ms, mean, docs + chat) | 0.00 | 6068.93 |
| System 1 shortlist inference calls | 0 | 36 |
| System 1 latency per shortlist inference (ms) | 0.00 | 8091.91 |
| System 1 inference failures; baseline fallback used | 0 | 0 |
| System 1 timeouts | 0 | 0 |
| System 1 oversized/truncated input skips | 0 | 0 |
| sections in final context | 12.08 | 11.67 |
| unrelated item rate | 0.89 | 0.89 |
| answer-bearing share of context | 0.11 | 0.10 |
| queries dropping a record for budget | 27 | 27 |
| mean total latency (ms) | 17.67 | 8109.18 |
| p50 total latency (ms) | 18.02 | 8264.62 |
| p95 total latency (ms) | 22.70 | 11474.70 |
| p95 total System 1 time per query (ms) | 0 | 11449.59 |
| mean local latency (ms) | 17.67 | 8109.18 |
| chat recall (4 queries) | 1.00 | 1.00 |
| fallback frequency | 0 | 0 |
| mean strategies run per query | 3 | 3 |
| navigation calls | 0 | 0 |
| navigation failures | 0 | 0 |
| navigation timeouts | 0 | 0 |

## Answers lost / gained relative to H (same questions)

- L H + local Laya System 1 reranking: budget 2000: lost 1, gained 0 (lost: which sqlite feature has to be enabled for the service); budget 20000: lost 1, gained 0 (lost: how many results does each keyword search return by default)

## Indexing

- H heading sections: FTS5 + semantic (product, no PageIndex): 6.06 s, 65 records
- L H + local Laya System 1 reranking: 5.31 s, 65 records

## Laya local resource snapshot

- Laya `convaiinnovations/laya-multilingual` revision `1720e3e3357cfe1e281542e223f8273b0890ca34`; package 0.4.6, 2.14.1+cu130, cpu; load 4017.8 ms; warmup 229.5 ms; checkpoint 614.0 MiB; RSS change on load +1631.2 MiB; RSS change on warmup +31.7 MiB.

## Saved Julia-1 reference

The table below is the previously recorded H/J run, not a fresh Julia rerun. Dataset and corpus hashes were checked against this run.

| budget | saved H answer rate | saved J answer rate | saved H MRR | saved J MRR | saved H latency (ms) | saved J latency (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 2000 | 0.417 | 0.083 | 0.361 | 0.083 | 49.8 | 708.9 |
| 20000 | 1.000 | 0.833 | 0.641 | 0.297 | 57.9 | 690.6 |
