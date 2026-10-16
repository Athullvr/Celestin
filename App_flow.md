# Celestin Application Flow

## Current interface

Celestin has no graphical application in this checkout. Its user-facing interaction is through MCP tools called by a local MCP-compatible assistant. The flow below describes that tool experience, not a designed web UI.

## First-time local setup

1. Install the package in a Python 3.10+ environment using the README instructions.
2. Register the `celestin` stdio server in the MCP client.
3. Select a writable SQLite path using `CELESTIN_DB_PATH` (or the supported legacy variable).
4. Configure `CELESTIN_LOCAL_PROJECT_ACCESS` with exact project names and read/write actions. If no policy grants the requested scope, data-tool calls are denied.
5. Restart the client if it was already running, then call `ping` to confirm server availability.

## Capture and preserve a decision

```text
Assistant / user
  └─ asks to retain a useful message or decision
       ├─ ingest_chat_message(project, conversation_id, role, content)
       │    └─ returns message_id and created_at
       └─ save_decision(project, key, value, source_message_id=message_id)
            └─ returns decision_id and status=draft
```

The source message must belong to the requested project. Saving a decision creates a draft; it does not approve it. The current MCP tool set has no approval or deprecation operation.

## Find past discussion

1. The assistant calls `search_chat_history` with project and query; `limit` is optional.
2. Celestin authorizes read access before retrieval.
3. The retrieval service searches project-scoped history and returns ranked records with source/conversation identifiers, timestamps, and scores.
4. If no records match, the client receives a successful empty result; backend failures are returned as errors rather than empty success.

## Build context for a new task

1. The assistant calls `retrieve_context(project, query, token_budget)`.
2. Celestin checks read access before querying.
3. The retrieval pipeline combines enabled strategies, prioritizes approved decisions, excludes draft/deprecated decisions by default, and assembles whole records within its documented estimated budget.
4. The response includes item IDs, source references, timestamps/status, rendered context, budget metadata, and eligible exclusions. Optional backends may add retrieval diagnostics or warnings.
5. The assistant uses the returned context and should preserve source traceability in its answer when relevant.

## Error and recovery paths

- Invalid fields or out-of-range limits/budgets: `INVALID_ARGUMENT`; correct the request.
- Project/action not on the local allowlist: `ACCESS_DENIED`; an administrator must update the local process configuration. Do not try alternate project names to bypass access control.
- Unknown or cross-project source message: `SOURCE_MESSAGE_NOT_FOUND`; do not save the decision without a valid source in that project.
- Storage failure: `STORAGE_ERROR`; do not claim a write succeeded.
- Retrieval dependency/service failure: a retrieval error category; optional semantic/PageIndex backends may instead provide documented fallback warnings.

## Collaboration boundary

Separate local SQLite files do not synchronize between machines. Cross-device shared memory requires a hosted authenticated service, which is not implemented by this flow. The hosted tenancy draft is planning material only.
