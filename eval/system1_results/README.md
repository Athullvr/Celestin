# Local System 1 comparison

H is the existing heading-section product path; J is the same path with local Julia-1 reranking. Each pair used the same frozen corpus, questions, BAAI/bge-small-en-v1.5 embeddings, FTS settings, and 2,000/20,000 context budgets. Dataset hashes are recorded in each JSON file and match the frozen sets. No model inference failures occurred.

| Dataset | Budget | H answer rate | J answer rate | H MRR | J MRR | H latency | J latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dev | 2,000 | 58.3% | 8.3% | 0.528 | 0.042 | 48 ms | 725 ms |
| Dev | 20,000 | 91.7% | 75.0% | 0.729 | 0.219 | 55 ms | 693 ms |
| Held-out | 2,000 | 41.7% | 8.3% | 0.361 | 0.083 | 50 ms | 709 ms |
| Held-out | 20,000 | 100% | 83.3% | 0.641 | 0.297 | 58 ms | 691 ms |
| Challenge | 2,000 | 33.3% | 16.7% | 0.333 | 0.083 | 62 ms | 745 ms |
| Challenge | 20,000 | 100% | 83.3% | 0.608 | 0.111 | 90 ms | 753 ms |

J did not improve answer-bearing context or MRR in any of the six comparisons. Chat recall stayed at 100%, but only 3–5 chat questions were available per set. Mean Julia-1 inference time was 594–654 ms per shortlist call; mean end-to-end request latency was 691–753 ms. Model startup was 13.6 s in this run, warmup 50 ms, checkpoint 550.5 MiB, and process RSS increased by about 996 MiB while loading/warming on CPU with four Torch threads. The environment emitted non-fatal Torch-extension and NVML warnings; CPU inference and strict model-output validation succeeded.

These results are negative evidence for this configuration, not proof that all System 1 models are ineffective. The local model was reliable but substantially slower and worse on answer-bearing evidence and MRR. Per-query records, run metadata, model checksums, and raw metrics are in [dev](dev/results.md), [held-out](heldout/results.md), and [challenge](rerank_challenge/results.md).
