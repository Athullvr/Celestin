# PageIndex document retrieval (optional)

Status: implemented, tested with a fake navigation model, **not measured with a real LLM** (no API key was available). It is off by default.

## What was evaluated

PageIndex (`pageindex` 0.4.0 on PyPI, MIT, https://github.com/VectifyAI/PageIndex) builds a heading tree per document and has an LLM navigate it instead of using vectors. Findings from reading the installed package:

| Question | Finding |
| --- | --- |
| Local mode input | The SDK's local mode takes **PDFs**. Markdown has a separate tree builder (`pageindex.page_index_md`) that works offline and without an LLM when summaries are off. |
| Conversation-style content | **Not supported directly.** A chat log has no headings, so the tree would be one flat level of messages. That adds nothing over FTS5/semantic search, and message titles carry no signal for an LLM. Conversations are therefore **not** indexed by PageIndex; the existing pipeline keeps handling chat. |
| Retrieval | The "reasoning" step is an LLM call over the outline. It needs a provider key, network, and costs tokens per query. |
| Dependencies | `pip install pageindex` pulls litellm, openai-agents, pypdfium2, PyPDF2 and others, so it is an optional extra. |
| Quirk | The Markdown parser treats a bold-only line (`**Windows PowerShell**`) as a level-1 heading, so a README's section paths can be misleading. Content is unaffected. |

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
- Routing: PageIndex runs when the project has indexed documents **and** the query has at least 3 words. Short or identifier-like queries (error codes, names) skip the model call and use FTS5 as before.
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

Other settings: `CELESTIN_PAGEINDEX_DB_PATH`, `CELESTIN_PAGEINDEX_TIMEOUT` (30 s), `CELESTIN_PAGEINDEX_MAX_SECTIONS` (5), `CELESTIN_PAGEINDEX_MAX_OUTLINE` (400 sections).

**Privacy and cost:** for every routed query the question and the outline (section paths plus the first ~200 characters of each section) are sent to the model provider. For the 7-document, 65-section evaluation corpus that is about 4,700 input tokens per query; it grows linearly up to the 400-section limit (about 30,000). Indexing itself needs no model and no network. Choose a local model through LiteLLM if documents are sensitive.

## Evaluation

Reproduce: `python eval/run_eval.py` (needs the `[semantic]` and `[pageindex]` extras and the cached embedding model; writes `eval/results.md`). Data: Celestin's own 7 Markdown documents (65 sections), 12 natural-language questions with content-based gold labels, plus 5 chat memories and 5 chat questions as a regression check.

Measured results (budget 20,000; budget 2,000 is in `eval/results.md`):

| System | answer in context | section source correct | mean context bytes | answer share of context | chat recall |
| --- | --- | --- | --- | --- | --- |
| A original: docs as messages, FTS5 | 0.00 | 0.00 | 1,564 | 0.00 | 0.20 |
| B A + semantic | 0.67 | 0.00 | 13,199 | 0.35 | 1.00 |
| F sections as messages + semantic (no PageIndex) | 0.92 | 0.92 | 17,777 | 0.09 | 1.00 |
| C PageIndex + FTS5, stand-in navigator | 0.50 | 0.50 | 4,673 | 0.15 | 0.20 |
| D PageIndex + semantic, stand-in navigator | 0.50 | 0.50 | 4,719 | 0.15 | 1.00 |
| E oracle navigator (upper bound) | 1.00 | 1.00 | 3,107 | 0.83 | 0.20 |

What this does and does not show:

- **Not measured:** C and D navigate with a lexical stand-in, not an LLM, and E is told the answer. **No real-LLM result exists, so there is no evidence yet that PageIndex improves retrieval here.** The opt-in test `tests/pageindex/test_live_llm.py` is written but has not been run.
- Measured: whole documents are poor retrieval units. At the default 2,000 budget systems A and B return no answer text, since whole documents are skipped for size. Heading-section granularity fixes that (F, C, D, E).
- Measured: simply ingesting heading sections as messages (F, which needs no LLM and no new backend) reaches 0.92 recall but fills the budget with weakly related sections (answer share 0.09). A perfect navigator (E) would give the same answers in about one sixth of the context. Whether an LLM gets close to E is the open question.
- Measured: adding PageIndex did not change chat recall (C/D match A/B, so no regression), and short identifier queries skip it.
- Latency: local steps take 1-10 ms; PageIndex adds one model round trip per routed query, which was **not measured**.
- Small, single-corpus eval (12 questions): treat differences of one question (0.08) as noise.

## Limitations

- Markdown only. PDFs need the SDK's own pipeline, and scanned PDFs need PageIndex Cloud; neither is integrated.
- One LLM call over the whole outline (max 400 sections), no per-document pre-selection and no summaries; large corpora are out of scope here.
- FTS5 still uses AND semantics, so long natural-language queries often miss in FTS5 (see system A).
- Section text is not truncated: a section bigger than the budget is excluded whole.
- Prompt injection: outline text from documents is placed in the model prompt. The reply is restricted to outline references, which limits the impact, but index only documents you trust.
- Highest-priority next step: run `celestin-docs`/`eval/run_eval.py` with a real navigation model (replace the stand-in) and compare against system F before recommending enabling it.
