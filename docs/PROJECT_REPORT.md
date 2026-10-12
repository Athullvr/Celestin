# Orbit project report (baseline for improvements)

Snapshot taken 2026-10-11 on branch `main` at commit `2165a79`. Facts below were checked against the repository and a test run; items marked "unverified" were not.

## 1. Summary

Orbit (package `orbit-memory-mcp` 0.1.0) is a local, stdio-only MCP server that gives AI agents project-scoped persistent memory. It stores chat messages and decisions in SQLite, searches them with FTS5, and builds a budgeted, traceable context bundle. Dependencies: `mcp>=1.0,<2.0` (runtime), `pytest` (test). Python >= 3.10.

## 2. Architecture

| Layer | Path | Role |
| --- | --- | --- |
| MCP server | `src/orbit/mcp_server/server.py` | FastMCP tools, input validation, stable error envelope (`INVALID_ARGUMENT`, `SOURCE_MESSAGE_NOT_FOUND`, `RETRIEVAL_UNAVAILABLE`, `STORAGE_ERROR`, `INTERNAL_ERROR`), sanitized logging |
| Service adapters | `mcp_server/persistence_services.py`, `retrieval_services.py` | Bridge MCP tools to repositories and retrieval |
| Retrieval | `src/orbit/retrieval/` (`fts.py`, `ranking.py`, `context_builder.py`, `service.py`) | FTS5 search, deterministic policy ranking, budgeted context assembly |
| Repositories | `src/orbit/repositories/` (`messages.py`, `decisions.py`, `_validation.py`) | Project-scoped data access and validation |
| Database | `src/orbit/database/engine.py` | SQLite connection/schema; `MEMORY_BRIDGE_DB_PATH`, default `data/memory_bridge.db` |

About 4,400 lines in total (source plus tests plus docs).

## 3. Public MCP tools

- `ping`
- `ingest_chat_message(project, conversation_id, role, content)`
- `save_decision(project, key, value, source_message_id)`: saves a draft decision.
- `search_chat_history(project, query, limit=10)`: limit 1-100.
- `retrieve_context(project, query, token_budget)`: budget 1-20,000 (UTF-8 bytes, not real tokens).

Entry points: `orbit` and the legacy alias `memory-bridge`.

## 4. Verification status

- Full suite: **107 passed** (`PATH=<venv>/bin:$PATH python -m pytest -q`), run in a throwaway venv in `/tmp`.
- Caveat: without the venv `bin` on `PATH`, `tests/test_mcp_protocol.py::test_startup_tool_discovery_ping_and_safe_validation` fails, because `shutil.which("memory-bridge")` returns `None`. This is an environment-dependence issue in the test and not a product bug. Running `pytest` with an unactivated venv also fails.
- Test coverage areas: database engine, messages, decisions, FTS, ranking, context builder, retrieval integration, MCP tools, protocol, persistence, and a two-process stdio end-to-end test.
- No lint, type-check, or CI configuration exists. `.github/` only has a PR template.

## 5. Known gaps and limitations

Functional:
1. **No approve/deprecate tool.** Decisions are saved as drafts and retrieval excludes drafts by default, so through MCP alone `retrieve_context` never returns a decision. The end-to-end test approves decisions through the repository directly. This is the biggest product gap.
2. No update/delete tools for messages or decisions, and no tool to list projects or conversations.
3. The budget counts bytes, not model tokens. Oversized records are skipped, not truncated.
4. Search is AND-only plain terms. Punctuation is discarded and there is no phrase, OR, or semantic search.
5. No project registry, so a mistyped project name looks like an empty project.

Security:
6. No caller authentication or identity-to-project authorization. `project` is only a caller-chosen scope. `docs/authorization-design.md` is a proposal and nothing is implemented.
7. Remote access (tunnel or hosted) is investigated only (`docs/phase-8-investigation.md`) and not started. Do not expose the server remotely.

Packaging and ops:
8. The default DB path depends on the working directory, which is easy to misconfigure for MCP clients.
9. Duplicate `DatabaseError`/`sqlite3.Error` handling is repeated in `server.py`.
10. `server.py` overrides FastMCP's private `_tool_manager`, which may break on SDK upgrades. The `mcp` dependency range is wide (`>=1.0,<2.0`).

## 6. Repository hygiene issues

- A stray tracked file named `h -u origin fix-ranking-null-source-tie` sits in the repo root. It looks like an accidental `git push` typo and should be removed.
- `.pytest_cache/` exists locally but is ignored and not tracked, which is fine.
- Local branches `retrival` and `fix-ranking-null-source-tie` plus several remote branches are merged or stale. `origin/HEAD` points to `retrival`, not `main`.
- The folder name `Devday ` has a trailing space, which can break scripts.

## 7. Hackathon submission status

`SUBMISSION.md` is **entirely TODO**: project name, description, repository URL, final commit SHA, demo steps, participants, checks, and checklist are all unfilled. The event ends 10:00 AM IST on 11 October 2026. `AI_USAGE.md` and `CHANGELOG.md` are current through the README update at 09:06 and have no entry for this report. `docs/examples/usage_example.py` exists and was not run.

## 8. Suggested improvements (priority order)

1. Complete `SUBMISSION.md` and record the final commit SHA. Do this first, given the deadline.
2. Add `approve_decision` and `deprecate_decision` MCP tools (the repository layer may already support status changes; verify), plus a test through the MCP boundary.
3. Remove the stray root file. Point `origin/HEAD` at `main` and prune stale branches (needs team agreement).
4. Make `test_mcp_protocol.py` resolve `memory-bridge` next to `sys.executable` so the test passes without PATH setup.
5. Add CI (GitHub Actions) that runs pytest on Python 3.10-3.12, plus a linter such as ruff.
6. Resolve the DB default path to a per-user data directory, or fail clearly when it is unwritable.
7. Add authentication and project authorization before any remote transport, following `docs/authorization-design.md`.
8. Improve retrieval: a real tokenizer for budgets, OR/phrase queries, and truncation of long records.
9. Refactor repeated error handling in `server.py` into one decorator, and test against the newest `mcp` 1.x.
10. Add a short demo script or recorded walkthrough to the README for judges.
