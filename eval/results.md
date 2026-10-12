# Evaluation results (12 document queries, 5 chat queries, 7 documents)

Navigation in C and D is a lexical stand-in, not an LLM; E is an oracle upper bound (see run_eval.py).


## Context budget 2000

| metric | A baseline (docs as messages, FTS5) | B baseline + semantic | F sections-as-messages + semantic (no PageIndex) | C PageIndex tree (stand-in navigator) + FTS5 | D PageIndex + semantic + FTS5 | E oracle navigator (upper bound) |
|---|---|---|---|---|---|---|
| answer text in context | 0.00 | 0.00 | 0.50 | 0.33 | 0.33 | 0.83 |
| document source correct | 0.00 | 0.00 | 0.92 | 0.58 | 0.58 | 0.83 |
| section source correct | 0.00 | 0.00 | 0.50 | 0.33 | 0.33 | 0.83 |
| MRR of answer item | 0.00 | 0.00 | 0.46 | 0.33 | 0.33 | 0.83 |
| mean context size (bytes) | 0 | 45.83 | 1694.42 | 1228.25 | 1275.08 | 1110.33 |
| answer-bearing share of context | 0.00 | 0.00 | 0.27 | 0.21 | 0.21 | 0.64 |
| queries that dropped a record for budget | 1 | 11 | 12 | 12 | 12 | 7 |
| mean latency (ms, warm) | 0.26 | 6.53 | 7.76 | 1.92 | 7.92 | 0.99 |
| chat-memory recall (5 queries) | 0.20 | 1.00 | 1.00 | 0.20 | 1.00 | 0.20 |

## Context budget 20000

| metric | A baseline (docs as messages, FTS5) | B baseline + semantic | F sections-as-messages + semantic (no PageIndex) | C PageIndex tree (stand-in navigator) + FTS5 | D PageIndex + semantic + FTS5 | E oracle navigator (upper bound) |
|---|---|---|---|---|---|---|
| answer text in context | 0.00 | 0.67 | 0.92 | 0.50 | 0.50 | 1.00 |
| document source correct | 0.00 | 0.67 | 1.00 | 0.92 | 0.92 | 1.00 |
| section source correct | 0.00 | 0.00 | 0.92 | 0.50 | 0.50 | 1.00 |
| MRR of answer item | 0.00 | 0.58 | 0.62 | 0.40 | 0.40 | 1.00 |
| mean context size (bytes) | 1564.17 | 13198.75 | 17777 | 4672.50 | 4719.33 | 3106.92 |
| answer-bearing share of context | 0.00 | 0.35 | 0.09 | 0.15 | 0.15 | 0.83 |
| queries that dropped a record for budget | 0 | 6 | 8 | 0 | 0 | 0 |
| mean latency (ms, warm) | 0.24 | 6.65 | 9.34 | 1.99 | 8.03 | 0.98 |
| chat-memory recall (5 queries) | 0.20 | 1.00 | 1.00 | 0.20 | 1.00 | 0.20 |

## Indexing cost (seconds, includes embeddings where used)

- A baseline (docs as messages, FTS5): 0.01
- B baseline + semantic: 1.58
- F sections-as-messages + semantic (no PageIndex): 6.85
- C PageIndex tree (stand-in navigator) + FTS5: 0.01
- D PageIndex + semantic + FTS5: 0.04
- E oracle navigator (upper bound): 0.01
