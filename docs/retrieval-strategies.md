# Retrieval strategies, heading sections and the adaptive selector

Four retrieval **strategies** (not agents) share one internal interface in `src/orbit/retrieval/strategies.py`:

| Strategy | Finds | Cost | Needs |
| --- | --- | --- | --- |
| `fts` | chat messages and decisions by keywords (strict first, bounded relaxation) | local, ~ms | nothing |
| `semantic` | messages and decisions by meaning | local embedding of the query | `[semantic]` extra, `CELESTIN_SEMANTIC_SEARCH=1` |
| `sections` | heading sections of indexed Markdown documents, by keywords and (if embedded) meaning | local | `celestin-docs index` (needs the `[pageindex]` extra only for its Markdown parser) |
| `pageindex` | sections chosen by an LLM reading the document outline | one model call per query | `CELESTIN_PAGEINDEX=1`, a model, credentials. **Off by default.** |

Each strategy returns normalized `Candidate` records: record id, record type (`chat_message`, `canonical_decision`, `document_section`), project, content, timestamp, source id, retrieval method, rank, engine-native score, decision status (from SQLite), and source metadata for sections (document, section path, line, node id, content hash). Engine scores are never compared across methods; candidates are merged by Reciprocal Rank Fusion (`-score` becomes `relevance_score`, lower is better) and then go through the unchanged policy and budget pipeline: approved decisions first, drafts and deprecated decisions excluded, project mismatch excluded, exact duplicates removed, UTF-8 byte budget enforced. With FTS5 alone, BM25 scores are kept exactly as before.

## Heading-section retrieval (product path)

- `celestin-docs index --project P docs/` splits Markdown into sections at valid heading boundaries (code fences ignored; bold-only lines are not headings when real `#` headings exist), keeps text before the first heading as `(preamble)`, and stores each section with its path, line, and the document's content hash in `<db>.pageindex.db`. A document without headings is one section.
- Keyword search uses an FTS5 table over that store with external content (`sections_fts`), so section text is stored once. It uses the same strict/stopword/relaxed tiers as chat search. Stores created before this feature are upgraded when opened for writing. Project filtering happens in the SQL join.
- Semantic search embeds sections into the existing vector index as a third record kind (own row-id range, so older vector files stay valid). `celestin-docs index|remove|rebuild|prune --yes` keep section embeddings in step automatically when semantic search is enabled; if the model is unavailable the change is reported as deferred and `celestin-index sync` repairs it. `celestin-index status|sync|rebuild` include sections whenever the document index exists.
- Idempotent indexing, atomic replacement of changed documents, explicit `prune`/`rebuild` maintenance and project isolation are tested. Deleted files are never removed implicitly.
- Sections are used by default **once documents have been indexed** (`CELESTIN_DOC_SECTIONS=0` disables). No documents indexed: nothing changes. Section items appear as `record_kind: "document_section"` with a `source` object; MCP tool names and schemas are unchanged.

## Selector

`CELESTIN_RETRIEVAL_SELECTOR` is `all` (default: every enabled strategy runs, as before) or `adaptive`. In adaptive mode `src/orbit/retrieval/selector.py` makes a deterministic, model-free plan, validates it against the strategies actually available, and runs FTS5 (always: it is local, keeps exact chat matches and approved decisions reachable), then the primary strategy, then at most one fallback if the primary found no strong evidence:

1. identifier, filename, error message, quoted phrase or very short query: `fts`;
2. documentation question spanning sections, PageIndex configured, documents indexed, budget and outline cost acceptable: `pageindex`;
3. question about an earlier discussion or decision ("did we", "decided", "earlier"): `semantic`;
4. other questions or documentation cues while documents are indexed: `sections` (fallback `pageindex` only for documentation cues and when justified, else `semantic`/`fts`);
5. other questions with semantic search available: `semantic`; otherwise `fts`.

"Strong evidence" means semantic hits (already above the similarity cut-off), PageIndex selections, or keyword hits where all (non-stopword) terms matched; the relaxed OR tier and empty results trigger the fallback. The decision, executed strategies and whether the fallback ran are reported under `retrieval.selector`. These are initial heuristics, not proven thresholds.

## Evaluation

Frozen corpus (7 documents, 65 sections) and 12 documentation questions plus 5 chat questions, hashed and pinned by a test. Reproduce:

```sh
python eval/run_eval.py                      # all local systems; real-LLM systems N and SN skipped without credentials
python eval/run_eval.py --fts-relax off      # strict FTS5 as in the first evaluation
CELESTIN_PAGEINDEX_MODEL=<litellm model> <provider key> python eval/run_eval.py --systems A,B,F,H,S,N,SN
```

Systems: A existing FTS5 (documents as one message each), B A plus semantic, F sections ingested as messages (the earlier harness baseline), **H the product heading-section path** (FTS5 + semantic over sections, all strategies), **S the product adaptive selector** (no PageIndex), N and SN PageIndex with a real LLM (not run), and diagnostics C, D, E (stand-in and oracle navigators) and Sd (selector with the stand-in navigator). Results at budget 20,000 (budget 2,000 in `eval/results.md`):

| System | answer in context | gold-section recall | section source correct | mean / median context bytes | unrelated item rate | chat recall | fallback rate | strategies run | latency ms (local, mean) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A existing FTS5 | 0.67 | 0.62 | 0.00 | 14,624 / 18,768 | 0.38 | 0.80 | 0 | 1 | 2.7 |
| B A + semantic | 0.75 | 0.66 | 0.00 | 16,999 / 18,695 | 0.57 | 1.00 | 0 | 2 | 10.1 |
| F sections as messages + semantic | 0.92 | 0.73 | 0.92 | 17,783 / 19,343 | 0.90 | 1.00 | 0 | 2 | 9.6 |
| H product heading sections | 0.92 | 0.73 | 0.92 | 17,744 / 19,562 | 0.90 | 1.00 | 0 | 3 | 16.9 |
| S adaptive selector | 0.92 | 0.73 | 0.92 | 17,719 / 19,495 | 0.90 | 1.00 | 0.08 | 2 | 12.0 |
| E oracle (diagnostic, upper bound) | 1.00 | 0.97 | 1.00 | 3,125 / 2,423 | 0.00 | 1.00 | 0 | 2 | 1.4 |

Findings, with the sample size (12 + 5 questions) in mind:

- The product heading-section path (H) reproduces the earlier harness baseline (F) to within bytes: 0.92 / 0.58 answer rate at 20,000 / 2,000.
- The selector (S) matched H on every quality metric and ran one strategy fewer (about 30% lower mean latency here). It did **not** reduce context size or unrelated content: both are the same as H. It saved compute, not noise, and cannot be called better than H on quality.
- Selector rules were revised during this work after failure analysis on this same dataset, so the final result is **not** an unbiased test. History: v1 (semantic for every question) scored 0.83 answer rate with a 92% fallback rate; sending questions to sections first fixed answers but cut chat recall to 0.40 (document sections crowded out chat memory); always running FTS5 restored chat recall to 1.00.
- A relative semantic margin of 0.08 (`CELESTIN_SEMANTIC_RELATIVE_MARGIN`, not a default) remains the only measured way to cut context noise (17,611 to 9,832 bytes, answer kept for 11 of 12; see `eval/results_f_sweep_strict_fts.md`).
- With stand-in navigation the selector never needed PageIndex on this dataset (Sd equals S), so the selector's PageIndex rules are untested against real navigation.
- **No real-LLM result exists** (no credentials), so the value of PageIndex, and of an LLM selector, remains unmeasured.

## LLM selector: not implemented

An LLM planner was assessed and deliberately not built. The deterministic selector already reaches the same quality as running everything on this dataset, so there is no measured gap for an extra model call to close, and the only strategy with a real model cost (PageIndex) has no real-LLM evidence yet. Revisit if `eval/run_eval.py --systems S,SN` with a real model shows queries where the deterministic plan misses answers that an LLM plan would catch, at a cost worth one more call per query. Any such planner should be feature-flagged, return schema-validated output restricted to the four strategy names with at most two searches, fall back to the deterministic plan without credentials, and log decisions but not queries or document text.

## Safety

The selector only chooses among retrieval strategies. It does not approve or modify memories, build SQL, or touch authorization; decision status always comes from SQLite and policy filtering is unchanged. Retrieved document sections are evidence returned inside the context bundle, never instructions. Routed PageIndex queries send the question and outline to the configured model provider (see `docs/pageindex.md`).

## Limitations

Markdown only; relaxed-FTS and selector thresholds were tuned on a 12-question set; semantic section search needs embeddings (`celestin-index sync`); section text larger than the budget is excluded whole; sections of one document are not merged back into parent context.
