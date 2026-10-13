# Context noise: diagnosis, section relevance filtering and results

Goal: more useful evidence per byte of context, without losing answers, chat recall, approved decisions or provenance. **Every control below is off by default; no default changed.**

## Diagnosis (where the noise comes from)

`python eval/diagnose.py --system S` traces the pipeline (counts, ranks, native scores, timings; no content). On the dev set, adaptive selector S, budget 20,000 (149 section items over 12 questions):

| Finding | Number |
| --- | --- |
| Section items that do not contain the answer | 134 of 149 (90%) |
| Sections found only by semantic search that were irrelevant | 125 of 132 |
| Irrelevant items at final position 1 / positions 4 and later | 4 of 12 / 110 of 113 |
| Section candidates per query before the budget / items that fit | 18.6 / 12.4 (context 89% full) |
| Candidates from keyword search (sections_fts) per query | 1.4 (semantic: 18.2) |
| Semantic similarity, relevant vs irrelevant sections | median 0.69 vs 0.64, minimum 0.62 vs 0.60 |
| Sections of 2,000+ bytes: share of section bytes / irrelevant | 32% / 18 of 21 |
| Near-duplicate sections inside one context (3-gram Jaccard >= 0.5) | 0 of 921 pairs |
| Exact duplicates, fusion or budget-truncation problems | none observed (fusion 0.1 ms; duplicates 0) |

Main cause: the absolute similarity cut-off (0.6) is low for sections, so about 18 weak semantic neighbours pass it, and the context builder then fills the budget in rank order, so everything after the top few is noise. Candidate fusion and deduplication are not the problem. Large sections inflate the cost of each wrong guess.

## Controls added

| Control | Setting | What it does |
| --- | --- | --- |
| Section margin (recommended opt-in) | `CELESTIN_SEMANTIC_SECTION_MARGIN=0.08` | Keeps semantic section hits within the margin of the best section hit (`score >= best - margin`, cosine similarities of one method only). Applies to sections only; chat messages and decisions are never trimmed by it. |
| Top-K cap (experimental) | `CELESTIN_SECTION_TOP_K=N` | Keeps the first N fused sections; sections with a strong keyword hit (all terms or all non-stopword terms matched) are exempt. |
| Excerpts (experimental) | `CELESTIN_SECTION_EXCERPT_BYTES=N` (>= 200) | Long sections are cut to the heading plus the paragraphs matching the query, with the original line ranges in `source.line_ranges` and `source.excerpted: true`. |
| Existing, all kinds | `CELESTIN_SEMANTIC_RELATIVE_MARGIN` | Same margin for every record kind (unchanged). |

Margin semantics (`src/orbit/semantic/margin.py`): `None` disables; an empty list stays empty; a single hit is always kept; ties with the best are all kept; zero and negative scores work because only differences matter; a missing or NaN score is never silently dropped. Scores are cosine similarities, not probabilities, and are never compared across retrieval methods. Margin and cap act before the unchanged policy and budget pipeline, so approved-decision priority, draft/deprecated exclusion, project isolation and the byte budget are untouched. `RetrievalService.last_diagnostics` (bounded, content-free) reports per-stage counts and timings and is not part of any MCP response.

## Evaluation

Dev set: the frozen 12 documentation + 5 chat questions (tuning set, hash unchanged). **Held-out set** (`eval/heldout.py`, 12 documentation + 4 chat questions over the same frozen corpus, written before any of these experiments ran and pinned by a test): evaluated once for all variants, not tuned on. All variants are S (adaptive selector, no PageIndex) plus the control. Budget 20,000, reduction is mean context bytes versus S:

| Variant | Answer in context (dev / held-out) | Mean bytes (dev / held-out) | Reduction (dev / held-out) | Unrelated item rate (dev / held-out) | Answers lost vs S (dev / held-out) |
| --- | --- | --- | --- | --- | --- |
| S (baseline) | 0.92 / 1.00 | 17,719 / 17,604 | 0 / 0 | 0.90 / 0.89 | - |
| S + margin 0.04 | 0.83 / 0.92 | 6,076 / 8,179 | 66% / 54% | 0.64 / 0.75 | 1 / 1 |
| **S + margin 0.08** | **0.92 / 1.00** | **11,448 / 13,657** | **35% / 22%** | **0.77 / 0.84** | **0 / 0** |
| S + margin 0.12 | 0.92 / 1.00 | 16,193 / 16,917 | 9% / 4% | 0.88 / 0.88 | 0 / 0 |
| S + top-3 | 0.83 / 0.83 | 5,088 / 5,138 | 71% / 71% | 0.66 / 0.69 | 1 / 2 |
| S + top-5 | 0.83 / 0.92 | 7,143 / 8,094 | 60% / 54% | 0.78 / 0.80 | 1 / 1 |
| S + top-8 | 0.92 / 0.92 | 10,928 / 11,552 | 38% / 34% | 0.84 / 0.85 | 0 / 1 |
| S + excerpts (1,200 B) | 0.92 / 0.92 | 16,355 / 16,420 | 8% / 7% | 0.91 / 0.90 | 0 / 1 |
| S + margin 0.08 + excerpts | 0.92 / 0.92 | 9,983 / 11,462 | 44% / 35% | 0.77 / 0.86 | 0 / 1 |

Chat recall stayed at 1.00 in every variant on both sets. Gold-section recall, median bytes, candidate counts before and after filtering (dev: 18.6 section candidates fall to 8.7 with margin 0.08), latency (about 9-10 ms versus 12-13 ms for S on this corpus, a side effect of fewer candidates, not a goal) and the budget-2,000 results are in `eval/results_noise_sweep.md` and `eval/results_noise_sweep_heldout.md`. At budget 2,000 all variants keep the same answers (dev 0.58, held-out 0.42, limited by section size, not by noise); margin 0.08 saves 10% / 5% there.

## Recommendations

- **Section margin 0.08: keep as a recommended opt-in, not a default.** It lost no answer on either set, cut 22-35% of the bytes and reduced irrelevant items, and it touches only semantic section hits. Evidence is 24 documentation questions on one 65-section corpus with one embedding model, and the margin's effect depends on that model's similarity scale, so it is exploratory. 0.04 lost an answer on both sets; 0.12 does almost nothing. Revisit making 0.08 a default after a larger, different corpus.
- **Top-K cap: reject as a default.** It trades answers for bytes (lost answers on held-out at K=3, 5, 8). Kept only as an experimental knob.
- **Excerpts: reject.** They barely reduce bytes (7-8%), lose gold-section recall and answers on held-out, and add source-line complexity. Kept as an experimental knob for very long sections; do not enable without measuring.
- **Duplicate suppression: not implemented.** Zero near-duplicate pairs and zero exact duplicates were observed.
- **Budget-aware subset selection: not implemented.** The only relevance signal is rank, so a smarter packing would optimize noise; the margin addresses the cause directly.
- **Remaining gap:** even with margin 0.08, 77-84% of selected sections do not contain the answer, versus 0% for the oracle. Better section ranking (for example a reranker) or an LLM navigator, evaluated with real credentials, is the next lever.

Limitations: small question sets (one question is 0.08), a single corpus, content-based relevance (a section "contains the answer" if it holds the gold string), tuning on the dev set only, and no real-LLM results.

Reproduce:

```sh
python eval/diagnose.py --system S
python eval/run_eval.py --noise-sweep                      # dev set
python eval/run_eval.py --noise-sweep --dataset heldout    # held-out set
```
