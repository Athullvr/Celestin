# PageIndex document retrieval (optional)

Status: implemented and tested with a fake navigation model; **real-LLM quality, latency and cost are still unmeasured** (no API key was available in either evaluation round). It is off by default.

## What was evaluated

PageIndex (`pageindex` 0.4.0 on PyPI, MIT, https://github.com/VectifyAI/PageIndex) builds a heading tree per document and has an LLM navigate it instead of using vectors. Findings from reading the installed package:

| Question | Finding |
| --- | --- |
| Local mode input | The SDK's local mode takes **PDFs**. Markdown has a separate tree builder (`pageindex.page_index_md`) that works offline and without an LLM when summaries are off. |
| Conversation-style content | **Not supported directly.** A chat log has no headings, so the tree would be one flat level of messages. That adds nothing over FTS5/semantic search, and message titles carry no signal for an LLM. Conversations are therefore **not** indexed by PageIndex; the existing pipeline keeps handling chat. |
| Retrieval | The "reasoning" step is an LLM call over the outline. It needs a provider key, network, and costs tokens per query. |
| Dependencies | `pip install pageindex` pulls litellm, openai-agents, pypdfium2, PyPDF2 and others, so it is an optional extra. |
| Quirk | The Markdown parser treats a bold-only line (`**Windows PowerShell**`) as a level-1 heading, which distorts section paths. Celestin now ignores bold-only lines as headings when the document has real `#` headings (they stay in the section text; tree schema `pageindex-md-v2` re-indexes older stores automatically). Documents with no `#` headings keep PageIndex's behavior. |

Chosen approach: a thin adaptation. Celestin uses PageIndex's Markdown parser for the tree, stores sections in a separate SQLite file, and navigates with its own small LLM call (single attempt, timeout, JSON reply) instead of the SDK's 10-retry loop, which could stall a stdio tool call.

## Architecture

```
celestin-docs index  -->  <db>.pageindex.db   (documents + sections; rebuildable from the files)
                              |
retrieve_context --> FTS5 + semantic (existing) --+
                 --> route(query) --> outline --> LLM picks sections --+--> RRF-style ranks --> policy --> budget
```

- Granularity: one document = one tree; one retrievable unit = one heading section. Chat messages stay individual records.
- Stable ids: `doc:<doc_key>#<node_id>`, where `doc_key` is the path relative to the indexed directory. Every section carries document, section path, line, node id and the document's content hash in `source`.
- Idempotent: re-indexing an unchanged file does nothing; a changed file (content hash or tree schema) is replaced atomically. Bad files fail individually and never stop the rest.
- Preserved source: the original text is stored in `documents.source_text`; text before the first heading becomes a `(preamble)` section.
- SQLite remains authoritative for chat and decisions. Documents live on disk; the index file can be deleted and rebuilt.

## Retrieval integration

- Only `retrieve_context` is extended. No tool was added; `search_chat_history` stays chat-only, since documents are not chat history. The five tool contracts are unchanged.
- Routing (`src/orbit/pageindex/routing.py`, deterministic, no model call): a query is navigated only when the project has indexed documents and none of these skip rules fires: identifier or filename lookup (error codes, snake_case, mixed letter-digit tokens, versions, paths), fewer than 3 words, context budget below 500, estimated outline above 40,000 tokens, or an approved decision that already matches every query term strictly (a cheap first stage: FTS5 runs before navigation). The reason is reported as `pageindex: "skipped: ..."`. The rules are heuristics checked by unit tests; their effect on real-LLM cost and quality is unmeasured.
- Merging: once anything is fused, messages, decisions and sections all use rank-based scores (`-1/(60+rank)`), so BM25 and rank scores are never mixed. Sections rank like any other record at the same rank.
- Policy kept: approved decisions still come first, drafts and deprecated decisions are still excluded, document sections have `status = null` and never outrank an approved decision. Exact duplicates are removed by the existing context builder, and the existing byte budget applies (a section larger than the budget is excluded whole, with reason `token_budget`).
- Response: document items have `record_kind: "document_section"`, `source_message_id: null` and a `source` object. The `retrieval` object (present when semantic search or PageIndex is enabled) gains `pageindex`: `used`, `no_documents`, `skipped: <reason>` or `unavailable: <reason>`.

## Failure behavior

Missing `litellm`, no model configured, no document index, a model error or timeout, an unparseable reply, or an oversized outline all produce `pageindex: "unavailable: ..."` plus a warning, and the rest of retrieval is unchanged. Model replies are parsed as outline references only; unknown references are discarded, so the model cannot invent a source.

## Install and configure

```sh
python -m pip install -e ".[pageindex]"
celestin-docs index --project my-project docs/ README.md      # idempotent
celestin-docs status --project my-project
export CELESTIN_PAGEINDEX=1
export CELESTIN_PAGEINDEX_MODEL=openai/gpt-4o-mini            # any LiteLLM model name
export OPENAI_API_KEY=...                                     # LiteLLM's standard variable for that provider
celestin-docs search --project my-project "why did we choose this storage layer"
```

For a coding agent, pass the same variables to the server, for example `codex mcp add celestin --env CELESTIN_DB_PATH=... --env CELESTIN_PAGEINDEX=1 --env CELESTIN_PAGEINDEX_MODEL=... --env OPENAI_API_KEY=... -- celestin`. The Codex integration itself was not exercised; the stdio server was tested with the MCP Python client only.

Other settings: `CELESTIN_PAGEINDEX_DB_PATH`, `CELESTIN_PAGEINDEX_TIMEOUT` (30 s), `CELESTIN_PAGEINDEX_MAX_SECTIONS` (5), `CELESTIN_PAGEINDEX_MAX_OUTLINE` (400 sections), `CELESTIN_PAGEINDEX_RETRIES` (extra attempts for transient errors; default 0; auth, not-found and oversized-prompt errors are never retried), `CELESTIN_PAGEINDEX_CACHE` (entries; default 64; 0 disables).

**Privacy and cost:** for every routed query the question and the outline (section paths plus the first ~200 characters of each section) are sent to the model provider. For the 7-document, 65-section evaluation corpus that is about 4,700 input tokens per query; it grows linearly up to the 400-section limit (about 30,000). Indexing itself needs no model and no network. Choose a local model through LiteLLM if documents are sensitive.

## Cost, latency and caching

- Each navigation records `elapsed_ms`, `cache_hit`, an estimated prompt size (`est_prompt_tokens`, characters/4, an estimate) and, when the provider reports it, observed `usage` (prompt and completion tokens). They appear under `retrieval.navigation` in `retrieve_context` responses. Logs contain error types only, never prompts, queries or document text (tested).
- The navigation cache is in memory per process, keyed by project, a fingerprint of the project's indexed documents (names, content hashes, tree schema), model name, section limit and the normalized query. Re-indexing a changed document changes the fingerprint, so stale entries are never reused; projects never share entries; failures are not cached.
- Prompt size on the evaluation corpus (7 documents, 65 sections): 19,013 characters, about 4,750 tokens estimated (measured from the real prompt text; provider-counted tokens need a real model). The estimate grows linearly with sections up to the 400-section limit.
- **Model latency, token usage and cost with a real model have not been measured** (no credentials). `eval/run_eval.py --systems N` records them when run with credentials.

## Index maintenance

- `celestin-docs index` never deletes anything. `status` flags documents whose source file is gone (`MISSING SOURCE`); `celestin-docs prune --project P` lists them and `--yes` removes only those index entries (source files are never touched).
- `celestin-docs rebuild --project P` re-derives every tree from the original text stored in the index, so it works without the source files.
- Each document is replaced in one transaction (an interrupted run leaves the previous version); the store uses WAL with a busy timeout, and concurrent writers from two connections were tested. Project isolation is enforced in every query.

## PDF support: assessed, deferred

`pageindex.flash.page_index_flash(path, summary=False, optimize=False)` builds a PDF tree without an LLM and returns page ranges (no text), so a loader would also need page-text extraction (`pypdfium2` is a PageIndex dependency). That is feasible, but it was not built: it needs real PDF fixtures and a page-reference model (`doc#page`) that the Markdown line-based references do not have, its output for scanned or image-heavy PDFs is `unreadable` without PageIndex Cloud (OCR), and it adds more dependencies for a use case with no demonstrated demand. Revisit if a real PDF corpus and a measured benefit from LLM navigation exist.

## Security notes

- Retrieved sections are evidence, not instructions. Section text is returned as data inside the context bundle and is never executed or used to change tool behavior. A coding agent should treat it like any quoted source and not as authority over its own instructions.
- Routed queries send the question and the outline (section paths plus the first ~200 characters of each section) to the configured model provider; nothing is sent unless `CELESTIN_PAGEINDEX=1` and a model is configured. Credentials are read from the provider's standard environment variables by LiteLLM and are never stored or logged by Celestin.
- Outline text from documents is placed in the model prompt, so a hostile document could try to steer navigation. Model replies are restricted to outline references (anything else is discarded), which limits the effect to selecting a different indexed section of the same project.
- The stdio MCP server was exercised with the Python MCP client with PageIndex disabled, enabled but unconfigured, and enabled with a fake model. A real Codex session was **not** tested.

## Evaluation

Reproduce: `python eval/run_eval.py` (needs the `[semantic]` and `[pageindex]` extras and the cached embedding model; writes `eval/results.md` and `.json`). Data: a frozen snapshot of Celestin's own 7 Markdown documents in `eval/corpus/` (65 sections), 12 natural-language questions with content-based gold labels, plus 5 chat memories and 5 chat questions as a regression check. The question set and corpus are hashed into every result file and pinned by a test, so a change cannot be made silently. Every system sees the same documents, chat memories and context budgets; the result files record the git commit, dataset hash, models, settings, per-query outcomes, failures and timeouts. Real-LLM system N (`--systems N`, needs `CELESTIN_PAGEINDEX_MODEL` plus provider credentials) is skipped with an explicit reason when credentials are missing, and fails with instructions if you ask for it explicitly or pass `--require-llm`.

Original comparison (strict FTS5 as in the first evaluation, `--fts-relax off`; `eval/results_strict_fts.md`; the corpus is now frozen, so budget-2,000 figures differ slightly from the first run, for example system C 0.25 instead of 0.33; the 20,000 figures reproduce):

| System (budget 20,000) | answer in context | section source correct | mean context bytes | answer share of context | chat recall |
| --- | --- | --- | --- | --- | --- |
| A original: docs as messages, FTS5 | 0.00 | 0.00 | 1,564 | 0.00 | 0.20 |
| B A + semantic | 0.67 | 0.00 | 13,199 | 0.35 | 1.00 |
| F sections as messages + semantic (no PageIndex) | 0.92 | 0.92 | 17,611 | 0.09 | 1.00 |
| C diagnostic: stand-in navigator + FTS5 | 0.50 | 0.50 | 4,766 | 0.15 | 0.20 |
| D diagnostic: stand-in navigator + semantic | 0.50 | 0.50 | 4,813 | 0.15 | 1.00 |
| E diagnostic: oracle navigator (upper bound) | 1.00 | 1.00 | 3,125 | 0.84 | 0.20 |

New default (bounded FTS5 relaxation on; `eval/results.md`), same corpus and questions:

| System (budget 20,000) | answer in context | mean context bytes | unrelated item rate | chat recall |
| --- | --- | --- | --- | --- |
| A | 0.67 (was 0.00) | 14,624 | 0.38 | 0.80 (was 0.20) |
| B | 0.75 (was 0.67) | 16,999 | 0.57 | 1.00 |
| F | 0.92 (unchanged) | 17,783 | 0.90 | 1.00 |
| C / D (diagnostic) | 0.50 / 0.50 (unchanged) | 4,766 / 4,813 | 0.83 | 1.00 / 1.00 |

Selectivity of the section baseline F (`python eval/run_eval.py --f-sweep --fts-relax off`; `eval/results_f_sweep_strict_fts.md`; budget 20,000):

| F variant | answer in context | gold-section recall | mean context bytes | unrelated item rate | answer share |
| --- | --- | --- | --- | --- | --- |
| F (default) | 0.92 | 0.72 | 17,611 | 0.91 | 0.09 |
| candidate_limit=10 | 0.92 | 0.72 | 13,721 | 0.88 | 0.11 |
| relative margin 0.12 | 0.92 | 0.68 | 15,427 | 0.90 | 0.09 |
| **relative margin 0.08** | **0.92** | 0.66 | **9,832** | **0.70** | **0.26** |
| relative margin 0.04 | 0.83 | 0.60 | 4,160 | 0.55 | 0.38 |
| candidate_limit=5 | 0.83 | 0.57 | 6,551 | 0.82 | 0.16 |

A relative margin of 0.08 keeps the answer in context for the same 11 of 12 questions with 44% fewer bytes, at some loss of gold-section recall (0.72 to 0.66). It is available as `CELESTIN_SEMANTIC_RELATIVE_MARGIN` but **not the default**: 12 questions cannot justify changing everyone's retrieval.

What this does and does not show:

- **Not measured:** C and D navigate with a lexical stand-in, not an LLM, and E is told the answer. **No real-LLM result exists, so there is no evidence yet that PageIndex improves retrieval here.** The opt-in test `tests/pageindex/test_live_llm.py` is written but has not been run.
- Measured: whole documents are poor retrieval units. At the default 2,000 budget systems A and B return no answer text, since whole documents are skipped for size. Heading-section granularity fixes that (F, C, D, E).
- Measured: simply ingesting heading sections as messages (F, which needs no LLM and no new backend) reaches 0.92 recall but fills the budget with weakly related sections (answer share 0.09). A perfect navigator (E) would give the same answers in about one sixth of the context. Whether an LLM gets close to E is the open question.
- Measured: adding PageIndex did not change chat recall (no regression), and identifier queries skip it. With the stand-in navigator all 12 document questions were routed (12 navigation calls); chat questions are not part of the call count.
- Measured: bounded FTS5 relaxation helps the existing pipeline most (system A answer rate 0.00 to 0.67, chat recall 0.20 to 0.80) and does not change F or the diagnostics; it also makes whole-document retrieval noisier (unrelated item rate 0.38 for A).
- Latency (observed, local): total retrieval 2-10 ms per query at this size (semantic systems about 8-10 ms); the model round trip PageIndex adds was **not measured**.
- Small, single-corpus eval (12 questions): treat differences of one question (0.08) as noise.

## Limitations

- Markdown only. PDFs need the SDK's own pipeline, and scanned PDFs need PageIndex Cloud; neither is integrated.
- One LLM call over the whole outline (max 400 sections), no per-document pre-selection and no summaries; large corpora are out of scope here.
- FTS5 is strict first; relaxation (stopword removal, then a bounded OR with a 60% term threshold that keeps identifiers required, only for queries with 3+ content terms) is a fallback tuned on this small corpus. `CELESTIN_FTS_RELAX=0` turns it off.
- Section text is not truncated: a section bigger than the budget is excluded whole.
- Prompt injection: outline text from documents is placed in the model prompt. The reply is restricted to outline references, which limits the impact, but index only documents you trust.
- Highest-priority next step: run `python eval/run_eval.py --systems A,B,F,N` with a real navigation model and compare N against F (and F with margin 0.08) before recommending PageIndex. Until then the evidence favors section-level semantic retrieval.
