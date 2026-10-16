# Celestin local Laya evaluation

## Outcome

The stock local Laya reranker did not show a consistent retrieval-quality improvement over H, and it was substantially slower on this CPU. Keep it experimental and opt-in; H remains the recommended default. The evaluation completed with zero Laya inference failures, timeouts, or over-budget skips.

| Frozen set | Budget | H answer / MRR / mean ms | Laya answer / MRR / mean ms | Saved Julia answer / MRR / mean ms |
|---|---:|---:|---:|---:|
| Dev | 2,000 | 0.583 / 0.528 / 13.9 | 0.333 / 0.333 / 8,696.9 | 0.083 / 0.042 / 724.7 |
| Dev | 20,000 | 0.917 / 0.729 / 15.0 | 0.917 / 0.542 / 8,733.3 | 0.750 / 0.219 / 692.8 |
| Held-out | 2,000 | 0.417 / 0.361 / 15.8 | 0.333 / 0.278 / 8,097.8 | 0.083 / 0.083 / 708.9 |
| Held-out | 20,000 | 1.000 / 0.641 / 17.7 | 0.917 / 0.708 / 8,109.2 | 0.833 / 0.297 / 690.6 |
| Challenge | 2,000 | 0.333 / 0.333 / 15.4 | 0.333 / 0.333 / 10,236.5 | 0.167 / 0.083 / 745.4 |
| Challenge | 20,000 | 1.000 / 0.608 / 17.6 | 1.000 / 0.529 / 10,206.6 | 0.833 / 0.111 / 753.1 |

Answer and MRR are fractions over document questions. Laya mean latency was about 8.1–10.2 seconds per request versus 14–18 ms for H and about 0.69–0.75 seconds for saved Julia. Chat recall stayed 1.0 for both H and L on all sets. Laya’s checkpoint was 614 MiB; loading added about 1.6 GiB RSS, with about 31 MiB more during warmup. The recorded runtime was Python 3.14.6, Laya 0.4.6, PyTorch 2.14.1+cu130, CPU, 10 threads. The saved Julia runs used Python 3.13.15 and a different PyTorch version, so Julia is historical context, not a controlled runtime comparison.

## Reproducibility and artifacts

Each dataset was evaluated with H and L on the same frozen corpus, questions, selector, semantic configuration, budgets, one local model warmup, and three measured passes. Corpus and question hashes matched the saved Julia artifacts. Full per-query JSON and rendered metrics are in `dev/`, `heldout/`, and `rerank_challenge/`; each JSON retains repeat-level results, latency percentiles, source/section recall, context size, unrelated-content rate, failures, runtime resources, and the historical Julia H/J reference.

The checkpoint was `convaiinnovations/laya-multilingual` revision `1720e3e3357cfe1e281542e223f8273b0890ca34`. The measured timeout is 30 seconds; a timed-out call falls back to baseline, and an in-flight call is not queued again. Model outputs remain transient. No MCP contract, SQLite schema, authorization, strategy routing, decision filtering, or final context budget changed for the evaluation.

Run from the repository root after installing the evaluation dependencies and locally caching the pinned Laya checkpoint:

```bash
python eval/run_eval.py --systems H,L --repeats 3 --dataset dev --out eval/laya_results/dev
python eval/run_eval.py --systems H,L --repeats 3 --dataset heldout --out eval/laya_results/heldout
python eval/run_eval.py --systems H,L --repeats 3 --dataset rerank_challenge --out eval/laya_results/rerank_challenge
```

## Test boundary

Automated checks cover local SQLite/process authorization, selector and retrieval-engine behavior, Laya boundaries, context assembly, and MCP protocol. The diagrams’ shared PostgreSQL memory, hosted identity, membership, and cloud authorization are not implemented here and were not tested; those remain future architecture, not a passing pipeline stage.
