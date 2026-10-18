# Resurrection integration acceptance-test plan

**Status: PROPOSED.** This file is a test plan, not a storage contract. The
accessible sources do not show ratification of the Capability 1 persistence,
candidate mapping, retry, conflict-edge, or additive MCP decisions below.

The current `MemoryStore` persists messages and decisions. The separate
`EvidenceLinkedMemoryStore` is a storage-neutral domain port; no production
adapter implements it in `src/`. Its protocol describes atomic knowledge plus
initial-evidence creation and atomic supersession. Those port requirements do
not prove a durable conversion transaction across capture provenance and
conflict associations. The existing cross-capability bridge and storage tests
use fakes.

## A. Executable against current domain interfaces and fakes

| Test | Prerequisite and expected behavior | Approval / limit |
|---|---|---|
| Read revocation at the Evidence service boundary: `tests/evidence/test_service.py::test_read_revocation_between_successive_reads_denies_before_store_access` | Mutable fake authorizer and counting fake store. A read succeeds while granted; after revocation, the next read raises before either protected-record or evidence reads. | **TESTED** as domain-service behavior. This does not verify live project membership or a hosted request path. |
| Capture review/replay invariants: `tests/capture/test_pipeline.py::test_approved_candidate_identical_retry_preserves_review_and_is_idempotent`, `test_approved_candidate_does_not_gain_evidence_after_review`, `test_materially_different_claim_does_not_inherit_terminal_review` | In-memory capture repository. Identical input preserves the approved candidate; changed evidence cannot mutate terminal review; materially changed claim produces a new pending candidate. | **TESTED** prototype behavior only. It does not specify C1 conversion idempotency or candidate identity semantics for shared storage. |
| Domain evidence/provenance mapping: `tests/capture/test_pipeline.py`, `tests/evidence/test_service.py`, `tests/retrieval/test_knowledge_state.py` | Use typed records and fake stores/readers. Preserve the modeled evidence IDs, source IDs, locator, revision/hash, timestamps, reference/verification states, capture provenance, and checker fields. Keep availability distinct from verification and retain absent optional metadata as absent. | **TESTED** at model/service seams. Durable adapter round-trip and the proposed `provenance_version` are not tested or approved. |
| Retrieval reader cardinality that the current seam can express: `tests/retrieval/test_knowledge_state.py::test_reader_is_project_scoped_and_does_not_change_candidate_order`, `test_reader_rejects_a_bundle_from_another_project` | Fake reader returns `None` or one bundle for `(project_id, record_kind, record_id)`. Missing state is omitted; a same-project bundle is attached; a foreign-project bundle is rejected. Candidate ranking/order stays unchanged. | **TESTED** seam behavior. The return type cannot encode “ambiguous”; authoritative mapping and its cardinality outcomes remain **BLOCKED**. |
| Hostile text and budget boundary: `tests/retrieval/test_knowledge_state.py::test_hostile_retrieved_text_cannot_change_jsonl_or_adjacent_evidence_metadata`, `test_knowledge_state_is_serialized_and_counted_in_the_context_budget`, `test_legacy_context_omits_optional_knowledge_state` | Context builder receives a fake candidate/envelope. JSON parsing keeps hostile text as content and preserves adjacent evidence fields; the complete rendered context, including the envelope, is counted by the configured counter; the legacy context remains unchanged when state is absent. | **TESTED** serialization/budget behavior only. No model-level prompt-injection resistance is established. |
| Pinned Git and worktree isolation: `tests/project_state/test_reconstructor.py::test_inspects_a_fixed_revision_and_ignores_worktree_changes` | Temporary repository has committed markers, modified tracked files, and an untracked file. Reconstruction of the pinned commit reports committed markers and excludes local changes without changing the worktree. | **TESTED** for Git-tree input. This does not pin the separately supplied knowledge records. |
| Dangling conflict pointer: `tests/project_state/test_reconstructor.py::test_dangling_capture_conflict_stays_unresolved_without_fabricating_counterpart` | Partial fake `list_records()` result includes a conflict reference to an unloaded candidate. Preserve the pointer, leave applicability unknown, and fabricate no counterpart or resolution. | **TESTED** for an incomplete source. The interface cannot distinguish “not loaded” from confirmed absence. |
| Cross-capability prototype: `tests/integration/test_capability_flow.py` | Test-only bridge exercises Capture → fake Evidence Memory → Reconstruction and sync separation. | **TESTED** harness only; not production persistence, authorization, or end-to-end integration. |

## B. Requires the agreed shared-memory contract and production adapter

Each expected result below is a test target to ratify; a documented proposal is
not an approved expectation. Do not implement these tests against a fake and
describe them as production acceptance.

| Test | Prerequisite and expected behavior to ratify | Approval status |
|---|---|---|
| Durable knowledge/evidence/provenance round-trip | Adapter and approved field/version contract. Create and read a record with multiple evidence references, capture/review provenance, IDs, lifecycle, verification/check metadata, conflicts, timestamps, and optional legacy fields. Assert every field and association survives exactly under the approved normalization/version rules. | The domain port requires provenance preservation or explicit rejection; schema, adapter, and provenance-version policy are **not approved**. |
| Retrieval-to-knowledge mapping: missing, unique, ambiguous, cross-project | Authoritative adapter for `(project_id, record_kind, record_id)`. Assert the exact approved outcome for zero, one, multiple, and foreign-project mappings; never select an arbitrary record or return cross-project data. | The proposal requires exactly one owner-approved mapping and asks for missing/ambiguous behavior. Response/error semantics are **not approved**. |
| Identical versus changed conversion retry | Durable conversion operation and agreed candidate identity/canonical payload. Identical retries should exercise the approved stable-result behavior; changed payloads should exercise the approved conflict/revision behavior without silent overwrite. | A proposal describes stable IDs for identical payload and a typed conflict for changed payload. Neither is ratified. |
| Concurrent conversion retry and stale review race | Durable candidate/review state plus transaction-bound conversion. Synchronize identical requests and conversion against a concurrent edit/reject/review-state change; assert one canonical outcome and the approved stale-state result. | Uniqueness/concurrency arbitration and compare-and-set/revision behavior are **not approved**. |
| Partial failure across record, evidence, and conflict associations | Adapter with injectable failures at each persistence stage. Assert only the approved atomic boundary and the caller-visible result after rollback or an uncertain commit. | The service port covers atomic `create_knowledge` plus initial evidence; conversion-wide atomicity including conflict links is only **proposed**. |
| Evidence availability changes independently of verification | Durable source resolver and persisted evidence row. Change source availability between reads; assert the approved read-time status refresh while the recorded verification/check metadata remains distinct. | Domain service behavior is tested with fakes; adapter/resolver behavior is not validated. |
| Conflict endpoint arrives later | Durable conflict representation and endpoint lookup. Convert one candidate with a dangling reference, later make the other endpoint available, and assert linkage preserves the original candidate IDs without selecting a winner or inventing resolution. | Pending endpoint registration/linking and symmetry are **proposed**, not approved. |
| Pinned Git plus project-scoped knowledge snapshot | Trusted project-to-repository resolver, authorized knowledge reader, and snapshot/version boundary. Assert the requested Git revision is used, memory belongs to the authorized project, and the approved consistency rule binds both inputs. | Current Git reader and `list_records()` seam are independent; no memory snapshot token or combined consistency rule is approved. |

## C. Requires the real runtime authorization path or consuming client

| Test | Prerequisite and expected behavior to ratify | Approval status |
|---|---|---|
| Project-membership revocation before a subsequent read | Production C1 adapter wired through the trusted principal and membership authorizer. Revoke membership after one successful read; the next request must be denied before protected knowledge/evidence is serialized. | Existing hosted-scope tests cover current message/decision operations with scripted/fake authorization data, not C1. The fake C1 domain boundary is tested; C1 runtime behavior is **BLOCKED**. |
| Legacy MCP compatibility and knowledge-state exposure | Running MCP adapter plus MCP owner’s decision on no exposure, a versioned subset, or capability negotiation. Verify `search_chat_history` and `retrieve_context` legacy item/response shapes remain compatible unless the approved version explicitly opts in. | Current adapter omits knowledge state. Any additive MCP exposure is **not approved**. |
| Runtime context-budget accounting | Approved retrieval/MCP exposure and the consuming client’s budget unit/counter. Assert the exact serialized context sent to the client—including any metadata—fits the approved budget and reports whether the count is estimated. | The internal builder counts the full rendered JSONL with a UTF-8 byte estimate by default. Runtime/model-token semantics are **not approved**. |
| Hostile retrieved text through the actual consuming client | Real consuming-agent harness, model/client, and tool-action recorder. Supply retrieved hostile text and verify it is treated as untrusted evidence, does not override privileged instructions, and causes no unauthorized tool action. | The repository has no consuming prompt assembler/model call. **BLOCKED**; JSON serialization tests are not a substitute. |

## Contract decisions needed before B/C acceptance

1. Authoritative mapping key, scope, and missing/unique/ambiguous/cross-project outcomes.
2. Candidate identity scope, approved revision identity, canonical payload fields, and revision/edit behavior.
3. Identical/changed/concurrent retry outcomes, uniqueness arbitration, and retryable database failures.
4. Conversion transaction boundary, rollback guarantees, and uncertain-commit behavior across evidence and conflicts.
5. Provenance version compatibility, typed evidence fields, timestamp normalization, and round-trip/reject behavior for unsupported data.
6. Dangling conflict identity/registration, symmetry, later endpoint linking, and explicit resolution outcomes/history.
7. Trusted principal and membership recheck semantics for each read/write, including authorization and data access transaction boundaries.
8. Whether knowledge state is ever exposed through MCP `items`, `retrieve_context`, `search_chat_history`, or a versioned/capability-negotiated subset.
9. Public context budget units and counter for metadata-expanded output.
10. Snapshot consistency between a pinned Git revision and the authorized knowledge view.
