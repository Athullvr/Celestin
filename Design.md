# Celestin Interaction Design

## Design status

Celestin currently exposes MCP tools rather than screens. This document defines the interaction and response principles for that interface. It is not a visual design system or a specification for a dashboard.

## Product principles

1. **Make capture explicit.** Persist a message only when the user or assistant intentionally invokes ingestion.
2. **Keep approval separate.** A stored decision is a draft until a separate, authorized workflow approves it. The current tools do not perform approval.
3. **Show provenance.** Return message/decision IDs, source links, project, conversation, status, timestamps, and ranking metadata where available.
4. **Scope every operation.** Keep reads and writes inside the requested project and check the process allowlist before data access.
5. **Explain failures safely.** Return stable error codes and useful next actions without SQL, stack traces, paths, secrets, or private conversation contents.
6. **Degrade optional retrieval carefully.** Preserve keyword search when optional semantic services fail; report fallback diagnostics without fabricating results.
7. **Be honest about budgets.** Label the current context budget as an estimate based on UTF-8 bytes, not an exact model-token count.

## Tool interaction conventions

- Tool names and arguments should be plain and predictable.
- Required strings are non-empty and bounded; role/status constraints follow the current contract.
- Writes return the stable record identifier immediately so a later action can refer to the saved record.
- Empty search/context results are valid successful outcomes and must be distinguishable from service errors.
- Search results are ranked relevance values, not probabilities.
- `retrieve_context` should preserve structured records in addition to rendered text so clients can inspect traceability.

## Information hierarchy for assistant clients

When presenting a retrieved context bundle, clients should prioritize:

1. Approved canonical decisions relevant to the current task.
2. Supporting source messages and their timestamps.
3. Other relevant message/document-section evidence.
4. Warnings, budget exclusions, and optional backend diagnostics.

The server implements retrieval selection and status filtering; the ordering above is guidance for consumers, not a separate UI implemented here.

## Future visual product

If a dashboard is approved later, it should make project scope and access status visible, distinguish drafts from approved/deprecated decisions, expose source provenance, and require confirmation plus authorization for archive or permanent purge. No screen layout, colors, typography, or interaction widgets are committed by this document.
