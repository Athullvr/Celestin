# Change log

Record each meaningful project change during the event, newest first. Update this file in the same commit as the change. Use a real timestamp with timezone, for example `YYYY-MM-DDTHH:MM:SS+05:30`.

## Event build log

## 2026-10-16T13:58:26+05:30 — Add project-scoped Neon agent tooling

- Changed: Added the Neon, Neon Postgres, and Neon Object Storage agent skills under `.agents/skills/`; configured the project Codex Neon MCP server using OAuth in `.codex/config.toml`; added the skill source lock file and README setup notes.
- Why: Make official Neon guidance and project-scoped Neon management tools available to contributors without storing an API key in the repository.
- Validation: Confirmed the skills CLI lists all three Neon skills at project scope and verified the generated Codex MCP entry contains only the Neon MCP URL. `git diff --check` was run after documentation updates.
- Limitations: The Neon CLI `skills` wrapper could not run with installed Node.js 22.18.0 (it requires 22.20+) and then reported that its external `skills` executable was unavailable. Used Neon's documented `npx skills add` fallback. Neon MCP OAuth sign-in must be completed by each Codex user on first use. No Neon project was linked or deployed; Celestin remains SQLite-backed.

## 2026-10-16T09:05:44+05:30 — Add Celestin product and build documents

- Changed: Added `PRD.md`, `TRD.md`, `App_flow.md`, `Design.md`, and `database_schema.md`; added a documentation index to `README.md` and recorded this contribution in `AI_USAGE.md`.
- Why: Give the team a consistent, implementation-grounded product, technical, interaction-flow, design, and schema handoff.
- Validation: Reviewed the docs against the checked-out README, MCP server, SQLite engine/repositories, and hosted schema draft; local Markdown links and `git diff --check` passed. No application tests were run for this documentation-only change.
- Limitations: The Orbit memory lookup for project `celestin` returned `ACCESS_DENIED`; no alternate project was queried. The docs describe the local MCP implementation and label the hosted PostgreSQL schema as draft/planning only. No runtime code or database was changed.

## 2026-10-14T20:26:50+05:30 — Add optional granular commit watcher

- Changed: Added the `commit_granular` custom agent, a PowerShell watcher with quiet-period dispatch and safety pauses, disposable watcher and agent test harnesses, and setup instructions in `AGENTS.md` and `README.md`.
- Why: Let Codex make separate local commits for independent completed changes while protecting pre-existing work, unrelated files, and remote Git state.
- Validation: `pwsh -NoProfile -File scripts/test-commit-watcher.ps1` — passed, including clean-start refusal, debounce, CLI failure, branch-change and index-lock pauses, remote-operation checks, and graceful stop. PowerShell parser checks and `git diff --check` passed.
- Limitations: `scripts/test-commit-agent.ps1` was attempted in a disposable repository but could not verify actual commits because the Codex subagent helper failed during setup (`helper_unknown_error: setup refresh had errors`; local `pwc-local` MCP connection was unavailable). The test harness is retained for an environment where the helper can start. Console Ctrl+C was verified by handler registration and cleanup code, not by injecting a real terminal signal.

## 2026-10-14T17:38:49+05:30 — Add provenance index and owner-concurrency validation requirements

- Changed: Added non-partial `project_memory(project_id, source_message_id)` to the hosted PostgreSQL schema draft; documented its provenance/FK-check purpose, the workspace-row lock/recheck protocol for owner changes, required concurrent-owner and hosted authorization tests, and the user-reported behavioral validation outcome. Clarified that the new index has not been applied to the already-used test database.
- Why: Cover the referencing-side FK index gap and make clear that the active-owner invariant needs serialized application transactions; accurately distinguish reported DB evidence from work independently verified in this update.
- Validation: Static SQL/documentation review and `git diff --check`; no database connection, schema execution, or test suite run.
- Limitations: User-reported validation of the previous draft was not independently rerun. The added index, owner concurrency, hosted application authorization, search/cache isolation, and purge authorization remain unverified or unimplemented.

## 2026-10-14T08:53:45+05:30 — Finalize hosted tenancy policy draft and validation plan

- Changed: Rewrote `docs/hosted-tenancy-spike.md` with the explicit-membership-and-grant matrix, ownership/archive/purge rules, enforcement boundaries, updated index review, synthetic PostgreSQL test cases and secure commands; corrected stale PostgreSQL environment notes. Designated `celestin` as the repository's canonical memory project ID in `README.md` per user instruction.
- Why: Turn the approved policy defaults into a reviewable schema-validation plan without implementing hosted runtime behavior.
- Validation: Documentation and SQL reviewed statically; `git diff --check` passed. No PostgreSQL schema command or test was run.
- Limitations: Disposable database credentials, purge policy, administrator permissions, service-identity scope, and live PostgreSQL constraint tests remain outstanding. Orbit memory retrieval for project `celestin` returned `ACCESS_DENIED`; no alternate project was queried.

## 2026-10-14T08:52:24+05:30 — Add archive-first retention to hosted schema draft

- Changed: Added archive and purge-eligibility timestamps to workspaces, projects, messages, and decisions; replaced cascading deletes with restrictive references; kept message provenance until an explicit purge or separately approved detachment; indexed workspace membership lookups and active-owner checks.
- Why: Prevent ordinary parent deletion from cascading into memory and preserve source links through archive periods.
- Validation: SQL reviewed statically; `git diff --check` passed. No SQL was executed against PostgreSQL.
- Limitations: Retention duration, purge authority, owner-transfer transaction, and purge audit process remain policy/application responsibilities and need team approval.

## 2026-10-14T08:51:25+05:30 — Scope hosted records and grants consistently

- Changed: Added workspace scope to hosted messages and decisions with composite project references; retained revoked grant rows; made service identity uniqueness workspace-scoped and recorded revocation timestamps; added indexes for grant foreign keys and removed the standalone project-memory project index.
- Why: Align hosted row relationships with tenant scope and the approved explicit-grant policy while preserving revocation history.
- Validation: SQL and constraints reviewed statically; `git diff --check` passed. PostgreSQL execution is still blocked on credentials for a disposable database.
- Limitations: Access decisions still require authenticated application authorization; this schema does not implement the hosted server. Lifecycle/delete behavior is addressed in the next draft revision.

## 2026-10-13T19:25:02+05:30 — Draft hosted tenancy schema spike

- Changed: Added `docs/hosted-tenancy-spike.md` and `docs/hosted-tenancy-schema.sql` describing a proposed workspace/project membership model and an empty-database PostgreSQL schema with project-scoped message/decision source references.
- Why: Establish a reviewable first step toward hosted shared memory while leaving the local SQLite schema, MCP contracts, and authorization behavior untouched.
- Validation: Reviewed schema relationships; full Python suite with `PYTHONPATH=src` — 245 passed, 1 failed, 15 skipped. The failure launches a stale globally installed `orbit.exe` instead of the current source package. `git diff --cached --check` passed.
- Limitations: PostgreSQL behavior was not tested because no PostgreSQL server is available and Docker Desktop's engine is stopped. The proposed membership defaults and legacy project mapping require team review; no application migration or hosted service is implemented.

## 2026-10-13T18:25:34+05:30 — Enforce local Celestin project access

- Changed: Added server-process project/action authorization before all four data tools; added the Celestin environment name with the Orbit variable as a fallback; updated MCP, stdio, persistence, and compatibility tests; documented access and compatibility; clarified the optional PageIndex query/outline data flow in the README.
- Why: Prevent a local MCP client from selecting an ungranted project through the `project` argument while retaining the current stdio architecture and legacy configuration.
- Validation: Clean Celestin editable install; focused MCP/authorization/compatibility checks — 36 passed; full suite — 246 passed, 20 skipped; `git diff --check` clean.
- Limitations: Stdio does not authenticate individual clients. All clients attached to the server process share its allowlist; this does not protect against untrusted same-user processes or authorize remote access.

## 2026-10-13T18:23:32+05:30 — Make database-path compatibility checks portable

- Changed: Normalize the displayed database path in `tests/test_celestin_rename.py` before comparing expected environment-variable values.
- Why: Windows renders path separators differently from the POSIX strings used by the compatibility cases.
- Validation: `python -m pytest -p no:cacheprovider -o addopts='' tests/test_celestin_rename.py` — 7 passed in the Celestin editable environment.
- Limitations: This changes test comparison only; database path resolution and behavior are unchanged.

## 2026-10-13T12:03:32+05:30 — Add an untuned reranking challenge set

- Changed: Added six documentation and three chat questions in `eval/rerank_challenge.py`, integrated the set and its pinned hash with the evaluation harness, recorded the full six-variant sweep and a separate four-variant lexical ablation in `eval/results_rerank_challenge*`, and made the chat-recall table labels reflect the set size. Updated the reranking analysis in `docs/context-optimization.md`.
- Why: Check the candidate ranking signal on questions added after the dev and held-out reranker comparisons.
- Validation: Reproduced S on dev and held-out (dataset hashes unchanged); ran all six variants on the challenge set. Focused reranker/evaluation tests passed (35). The broader suite passed with documented live-LLM and stdio subprocess exclusions; full optional-dependency collection errors in installed `litellm` during its background cost-map retry.
- Limitations: Challenge set is small and cannot replace the two original frozen evaluations. Each variant answered all six documentation questions; chat recall was 2/3 for every variant. Real-LLM evaluation was not run. No commit or push made.

## 2026-10-13T12:06:52+05:30 — Evaluate opt-in section reranking

- Changed: Audited the already-committed reranker at `a80e7b8`; added development, held-out, and new-query challenge evaluation artifacts; recorded full candidate ordering and chat query outcomes; added a pinned six-question documentation challenge set; documented controls and findings; corrected service-test queries so they retrieve multiple sections and the approved decision under test. No retrieval behavior, defaults, dependencies, frozen datasets, or MCP contracts changed.
- Why: Determine whether candidate reordering improves answer-bearing evidence per byte on both frozen question sets.
- Validation: Reproduced S and S+0.08 baselines at budget 20,000 with frozen dataset hashes unchanged; evaluated reranking variants on dev and held-out and then on six new documentation questions plus three chat questions. Margin+cross-encoder RRF+top-8 improved measured gold evidence per byte without answer loss in these runs, but top-8 was selected after prior held-out inspection. All 35 targeted reranker/evaluation tests passed. Broad tests passed with optional dependencies after excluding the live-LLM import and three stdio subprocess tests; the no-optional-dependency suite exited successfully with two protocol test files excluded. Full unfiltered collection failed in the installed optional `litellm` module; real-LLM retrieval was not run.
- Limitations: The new challenge has six document questions on the same corpus; it is too small to justify changing defaults. Plain cross-encoder scoring lost one held-out answer. All controls remain opt-in. Memory was not measured; the local cross-encoder artifact was 90.9 MB. No commit or push made.

## 2026-10-13T11:06:45+05:30 — Context-noise diagnosis and opt-in section relevance filtering

- Changed: Added `RetrievalService.last_diagnostics` (bounded, content-free stage trace) and `eval/diagnose.py`; section-only semantic margin (`CELESTIN_SEMANTIC_SECTION_MARGIN`, shared `semantic/margin.py`), optional section top-K cap (`CELESTIN_SECTION_TOP_K`) and query-focused excerpts (`CELESTIN_SECTION_EXCERPT_BYTES`) in `retrieval/relevance.py`; evaluation `--noise-sweep` and `--dataset heldout` with a frozen held-out set (`eval/heldout.py`) and answers-lost reporting. No defaults changed; MCP tools and schemas unchanged.
- Why: 90% of section items in the context were irrelevant because weak semantic neighbours pass the 0.6 cut-off and the budget is filled in rank order.
- Validation: see the test counts in the final report; sweeps run on the dev and held-out sets. Section margin 0.08 lost no answer on either set and cut 22-35% of bytes; top-K and excerpts lost answers and are not recommended.
- Limitations: 24 documentation questions on one corpus; the margin depends on the embedding model's similarity scale; no real-LLM evidence; duplicate suppression and budget-aware packing were not implemented because the diagnosis showed no duplicates and no usable relevance signal.

## 2026-10-13T10:31:53+05:30 — Heading-section retrieval, strategy interface and adaptive selector

- Changed: Heading-section retrieval is now a product path (`celestin-docs` store gains an external-content FTS5 index and section embeddings as a third vector kind; `celestin-index` and `celestin-docs` keep them in step). New `retrieval/strategies.py` (FTS5, semantic, sections, PageIndex behind one `Candidate`/`StrategyResult` interface) and `retrieval/selector.py` (deterministic primary + one fallback); `RetrievalService.retrieve_context` now runs strategies and fuses candidates (BM25 kept for FTS-only). `CELESTIN_RETRIEVAL_SELECTOR=adaptive` opts in (default `all`); `CELESTIN_DOC_SECTIONS=0` disables sections. The FTS tier logic is shared (`tiered_match`). Eval harness gains systems H, S, SN, Sd, median bytes, fallback and strategy counts.
- Why: Make the strongest measured baseline (heading sections) available in the product and test whether routing helps.
- Validation: see the test counts in the final report below; evaluation rerun on the frozen corpus (dataset hash unchanged). The adaptive selector matched H on answer-in-context (0.92) with one strategy fewer and did not reduce context size.
- Limitations: Selector rules were revised after failure analysis on the same 12 questions; no real-LLM evidence; an LLM selector was assessed and not built. A behavior change: users who already ran `celestin-docs index` now also get section results unless `CELESTIN_DOC_SECTIONS=0`.

## 2026-10-12T22:16:12+05:30 — Trustworthy evaluation, bounded FTS5 relaxation, PageIndex routing, cost instrumentation and maintenance

- Changed: `eval/run_eval.py` rewritten (frozen corpus in `eval/corpus/`, hashed dataset, per-query records, failure/timeout counts, observed vs estimated tokens, cost estimate, run metadata, real-LLM system N with credential checks, F selectivity sweep, `--fts-relax`); bounded FTS5 relaxation (stopword tier, then OR tier with a 60% threshold and required identifiers; quoted phrases; `CELESTIN_FTS_RELAX=0` disables); optional `CELESTIN_SEMANTIC_RELATIVE_MARGIN`; deterministic PageIndex routing policy with a cheap first stage; navigation stats, bounded retries and a project/index-version-keyed cache; bold-only-heading fix (tree schema v2); `celestin-docs prune|rebuild` and deleted-source reporting; WAL for the document store; Orbit skill text renamed to Celestin (skill id `orbit` kept). PDF support assessed and deferred.
- Why: Make retrieval measurements trustworthy and cut unnecessary navigation cost while keeping PageIndex optional and off by default.
- Validation: with all extras 275 passed, 2 skipped (opt-in real-model and live-LLM tests); without extras 196 passed, 14 skipped. Evaluation rerun on the frozen corpus: strict-FTS results reproduce the first evaluation at budget 20,000; relaxation lifted the existing pipeline (answer rate 0.00 to 0.67, chat recall 0.20 to 0.80).
- Limitations: Still no real-LLM run (no credentials), so PageIndex's real quality, latency and cost are unmeasured and the strongest measured practical baseline remains section-level semantic retrieval. Relaxation thresholds and routing rules were tuned on 12 questions. A real Codex session was not tested.

## 2026-10-12T21:38:30+05:30 — Optional PageIndex document retrieval

- Changed: Added `src/orbit/pageindex/` (Markdown section trees via PageIndex's parser, separate rebuildable store, LLM outline navigator, backend, `celestin-docs` CLI), a `document_section` record kind, and PageIndex routing/fusion in `RetrievalService.retrieve_context`. `retrieve_context` responses show `source` for sections and `retrieval.pageindex` when enabled; no tool contracts changed. New extra `pageindex`. Added `eval/` (dataset, runner, results) and `docs/pageindex.md`. Test isolation fix: tests set `orbit.database.engine.DB_PATH` because it is read at import time.
- Why: Evaluate hierarchical document retrieval for long documents that chat-message storage and whole-record budgeting handle poorly.
- Validation: with all extras, 216 passed and 2 skipped (opt-in real-model and live-LLM tests). Without optional extras, 150 passed and 9 skipped. The stdio server was exercised with PageIndex enabled but unconfigured (all five tools worked). `python eval/run_eval.py` ran (results in `eval/results.md`).
- Limitations: No LLM API key was available, so navigation quality is unmeasured; the evaluation uses a lexical stand-in and an oracle upper bound and shows no evidence yet that PageIndex beats simple section chunking with the existing semantic search. Markdown only; conversations are not indexed by PageIndex by design. `.agents/skills/orbit/SKILL.md` still uses the Orbit name (not changed here).

## 2026-10-11T22:17:11+05:30 — Push reconciled branch to the fork

- Changed: Pushed merge commit `441cb0a` to `origin/main` (`67ddd33..441cb0a`) and set local `main` to track the fork.
- Why: Publish the reconciled histories to the fork so the branch can continue from the synchronized base.
- Validation: Git reported a successful push and configured `origin/main` as the tracking branch.
- Limitations: No application code changed; no application tests were run for this Git and documentation update.

## 2026-10-11T21:57:40+05:30 — Reconcile fork history and integrate the memory skill

- Changed: Merged the three upstream commits into the four-commit Celestin branch, preserving both histories; integrated `.agents/skills/orbit/SKILL.md` and its `AGENTS.md`/README guidance, combined both development logs, and aligned the README's MCP inspection command with the configured `celestin` server name.
- Why: Bring the fork up to date while retaining the Celestin rename and semantic retrieval work already on the branch.
- Validation: Reviewed the merge tree and documentation consistency; `git diff --check` and local Markdown link checks run after resolution. No tests run for this Git and documentation change.
- Limitations: The request did not specify another application feature, so no application code was changed. The repository still has no canonical project identifier for the memory skill.

## 2026-10-11T20:20:22+05:30 — Rename to Celestin and add hybrid semantic retrieval

- Changed: Renamed the product to Celestin (distribution `celestin-memory` 0.2.0, commands `celestin` and `celestin-index`, MCP server name and `ping` text, README and docs). The `orbit` and `memory-bridge` commands, the `orbit` import package, all MCP tool names, the SQLite schema and `MEMORY_BRIDGE_DB_PATH` are kept for compatibility; `CELESTIN_DB_PATH` takes precedence when set. Added an opt-in semantic layer (`src/orbit/semantic/`: fastembed provider, sqlite-vec index in a separate file, reconciliation indexer, `celestin-index` CLI) and Reciprocal Rank Fusion in `RetrievalService` (`src/orbit/retrieval/hybrid.py`). Enabled with `CELESTIN_SEMANTIC_SEARCH=1`; when enabled, tool responses gain a `retrieval` object (`mode`, `warnings`). Tests now locate console scripts next to the interpreter, so they pass without activating the venv.
- Why: Rebrand the product and let reworded queries find saved memories without losing exact FTS5 matching.
- Validation: Full suite with the semantic extra: 171 passed, 1 skipped (opt-in real-model test). The real-model test passed separately with `CELESTIN_RUN_MODEL_TESTS=1`. A venv without the extra: all non-semantic tests passed and the semantic tests skipped. A manual run against a disposable database with the real model found the reworded memory, kept the exact error-code match first, excluded other projects, and returned nothing for an unrelated query.
- Limitations: No plugin manifest, marketplace entry or skill exists in the repository, so none was renamed. The similarity cut-off (0.6) comes from a small probe of one model and should be tuned. No MCP tool approves decisions, so approved decisions need `celestin-index sync`. Not tested on Windows/macOS. Vector search is brute-force. Remote embedding providers are not implemented. Historical entries below keep the Orbit name.

## 2026-10-11T09:11:48+05:30 — Add reusable Orbit project-memory skill

- Changed: Added `.agents/skills/orbit/SKILL.md`, guidance in `AGENTS.md`, and README setup, invocation, and teammate instructions.
- Why: Give Codex a reusable workflow for safe project-scoped retrieval and explicitly approved saves through the existing Orbit MCP tools.
- Validation: Skill metadata validator passed; `python -m pytest -p no:cacheprovider -o addopts=''` on the rebased branch: 107 passed; `git diff --check` clean.
- Limitations: No canonical project identifier is documented for this repository. This adds no project ID, MCP configuration, credentials, or per-user authorization.

## 2026-10-11T09:06:01+05:30 — Align README with the implemented project

- Changed: Rewrote `README.md` with cross-platform installation, database configuration, Codex CLI setup, MCP tool examples, and current behavior and limitations.
- Why: The previous setup was Windows-only and omitted important implementation details for running and demonstrating Orbit.
- Validation: Compared instructions against `pyproject.toml`, the SQLite engine, MCP server, and retrieval documentation; checked Markdown links and `git diff --check`.
- Limitations: No application UI or hosted demo is implemented; the demo uses a connected local MCP client.

## 2026-10-11T05:18:21+05:30 — Validate end-to-end MCP memory workflow

- Changed: Added a two-process stdio MCP integration test using a disposable SQLite database; fixed FastMCP error wrapping so `SOURCE_MESSAGE_NOT_FOUND` keeps its stable category over the protocol.
- Why: Validate persistence across a server restart, cross-session retrieval, project scoping, lifecycle filtering, and the public error envelope without touching project data.
- Validation: `python -m pytest -p no:cacheprovider -o addopts=''` — 107 passed; `git diff --check` — clean. The focused test also passed independently.
- Limitations: No authenticated identity or identity-to-project authorization exists. `project` remains a caller-selected scope; current isolation prevents cross-project record mixing but does not authorize callers. Decision approval was performed through the repository in the test fixture because no approval MCP tool exists.

## Template setup — 10 October 2026

- Changed: Added the event README, rules, agent guide, change log, AI usage record, submission checklist, Git ignore rules, and pull request checklist.
- Why: Give participants a consistent starting point for event rules, basic coding patterns, documented changes, and regular commits.
- Validation: Checked local Markdown links, event detail consistency, required documents, and diff whitespace before publishing.
- Limitations: Documentation scaffolding only; no participant project, application, or working demo is included. GitHub publication and template status are verified separately after creation.
