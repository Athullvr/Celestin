# Celestin Product Requirements Document

## Status and scope

This PRD describes the implemented local MVP and separates future hosted goals from current behavior. The current product is a Python MCP server used by coding and research assistants; it does not include a graphical interface or hosted multi-user service.

## Problem

AI assistants lose useful project context between chats and tools. Users need a project-scoped place to persist selected messages and decisions, search previous work, and provide a bounded, traceable context bundle to a later session.

## Users

- Developers or researchers using MCP-compatible assistants.
- Local agents that need durable project context across sessions.
- Project collaborators who operate a shared hosted service in a future release (planned, not implemented in the current runtime).

## Product goals

1. Persist chat messages and decision drafts locally with project and conversation scope.
2. Find relevant history through predictable keyword search and optional retrieval extensions.
3. Return source IDs, timestamps, status, and bounded context so assistants can trace what they use.
4. Make local setup reproducible and keep existing Orbit command, import, and database-path compatibility.
5. Fail closed when local project access is not configured.

## Current MVP requirements

| Capability | Requirement | Current behavior |
|---|---|---|
| Health | An MCP client can check that the server responds. | `ping` returns a health message. |
| Ingestion | Store a validated message under a project and conversation. | `ingest_chat_message` returns a message ID and UTC creation timestamp. |
| Decision capture | Save a decision linked to a source message in the same project. | `save_decision` creates or updates a draft; approval is not a tool operation. |
| History search | Search message content within one project. | `search_chat_history` returns ranked messages and provenance fields. |
| Context retrieval | Return useful, traceable records under a requested budget. | `retrieve_context` returns items, rendered context, estimate metadata, exclusions, and optional retrieval diagnostics. |
| Access | Prevent an unconfigured local process from accessing project data. | A process-level project/action allowlist is checked before data calls. |

## Non-functional requirements

- Local-first: SQLite is the runtime source of truth; the server uses stdio.
- Data isolation: retrieval and persistence queries are project-scoped.
- Safe failures: malformed input, denied access, missing source messages, and storage/retrieval failures have stable error categories without leaking internals.
- Traceability: results retain IDs, project, source/conversation, status, and timestamps where applicable.
- Optionality: semantic and PageIndex features remain opt-in and degrade with warnings where documented.
- Compatibility: preserve `orbit` package/imports, `orbit` and `memory-bridge` executable aliases, and `MEMORY_BRIDGE_DB_PATH`; `CELESTIN_DB_PATH` takes precedence.

## Out of scope for the current MVP

- A web dashboard or GUI.
- Authenticated multi-user identity, remote MCP transport, or hosted project authorization.
- Automatic approval of captured decisions.
- Automatic import of other assistants' chat histories.
- PostgreSQL as an application storage backend. The hosted tenancy SQL under `docs/` is a design/validation artifact, not the current runtime schema.

## Success criteria

- A local MCP client can discover and call the tools over stdio.
- Ingested messages and decisions persist in SQLite and can be found by later sessions.
- Search and context results stay within the requested project and preserve available provenance.
- Invalid inputs and denied projects fail predictably.
- Setup and limitations are accurately described in the README.

## Open product decisions

- Who may approve, deprecate, archive, and purge canonical knowledge in a hosted product.
- Hosted identity provider and how workspace memberships and explicit project grants are administered.
- Retention duration, legal-hold behavior, and audit requirements before permanent purge.
- Whether a future user interface is needed; none is specified by the current product.
