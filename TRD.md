# TRD: Local System 1 Retrieval

## Design and compatibility

The existing path stays default. `CELESTIN_RETRIEVAL_PATH=system1` reranks up to 20 authorized candidates per record type, preserving baseline score slots, strict-FTS hits, overflow order, provenance, and context assembly. Groups under two bypass the model. `search_chat_history`, MCP/SQLite schemas, authorization, and decision filters are unchanged; the model returns choices only.

## Runtime and failure behavior

Julia-1’s local runtime and checkpoint are pinned to revision `a85b127321d580d65176c89ced8273f305745d85`. The optional dependency supports Python 3.11–3.13 and loads once per process; runtime, tokenizer/configuration, and checkpoint checksums are verified. CPU inference passed on Python 3.13.15, Transformers 5.0.0, four Torch threads. Missing/mismatched artifacts or inference errors retain baseline order with a content-free warning. PageIndex is unchanged; no training or hosted inference is included.

## Evaluation

Paired H/J runs used the same frozen dev, held-out, and challenge questions and 2,000/20,000-byte budgets. J had lower answer-in-context and MRR in all six comparisons, with zero inference failures. Mean end-to-end latency was 691–753 ms for J versus 48–90 ms for H. The checkpoint is 550.5 MiB; load/warmup increased RSS by about 996 MiB. This configuration is not an improvement and stays opt-in. See [full results](eval/system1_results/README.md).
