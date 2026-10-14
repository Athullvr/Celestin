# Automatic Knowledge Capture prototype

## Status and boundary

`orbit.capture.KnowledgeCapturePipeline` is an isolated deterministic prototype.
It accepts only an explicitly supplied `CaptureInput`; it does not intercept
conversations, agent events, or repository activity. No LLM extractor currently
exists that is suitable for this job. PageIndex's optional model call navigates
document outlines and is not reused for knowledge extraction.

The pipeline is bound to one configured project identifier and rejects an input
whose project differs. This is a local data-isolation check, not authentication
or authorization. Callers must obtain trusted project scope before hosted
ingestion is considered. The prototype does not write to SQLite, PostgreSQL,
Capability 1, or MCP.

## Input and extraction

Input source types are `conversation_summary` and `execution_report`. Each
input has a required project ID and stable source ID, optional timezone-aware
timestamp/revision and Capability 1 `EvidenceSource` values, and either text or
structured `CaptureEvent` values. Text is limited to 100,000 characters,
structured input to 200 events, and each candidate claim to 2,000 characters.

Text extraction recognizes only explicit labeled lines, for example:

```text
Decision [storage]: Use SQLite for local state because it works offline.
Discovery: The index supports strict and relaxed FTS queries.
Bug fix: Normalize a path before computing its cache key.
Completed: Add project-scoped authorization checks.
Incomplete: Finish the PostgreSQL adapter integration.
Blocker: Waiting for an agreed evidence persistence contract.
Constraint: Preserve existing MCP tool arguments.
Implementation detail: Inspect files at a pinned Git revision.
```

`[storage]` is an optional explicit conflict key. Candidates with the same
category and conflict key but different normalized claims are all kept and
linked as alternatives. There is no semantic conflict detector. Structured
events can provide the category, claim, conflict key, evidence, and locator
directly. Unlabeled prose is ignored; no decision, completion, rationale, or
test result is inferred from it.

The pipeline stores candidate text, source IDs/locators, optional evidence
references, and review metadata only. It does not retain the supplied summary
or full execution report. Secret-like candidate statements and evidence
references matching common credential patterns are suppressed; suppression
records contain the source locator and reason but not the candidate text. This
pattern check is a safeguard, not a general secret scanner. Callers should
still avoid sending secrets.

## Candidate identity and review

Candidate IDs are deterministic for the project, category, normalized claim,
and optional conflict key. Whitespace/case-normalized repeats merge source and
evidence references. Replaying the same input is idempotent within the in-memory
repository; a new source with the same claim adds provenance to the same
candidate. Distinct claims remain separate, including conflicting claims.

New candidates start `pending_review` and `unverified`. Uncertainty words mark
the candidate `uncertain`, but do not change the claim to a fact. `unqualified`
only means the source text contained no recognized uncertainty phrase; it is
not a confidence or verification result. Reviewers can edit pending candidates,
request evidence, approve, or reject them. Candidate edits retain the original
claim and source links. Rejected and approved entries are terminal in this
prototype. Reviewer IDs and timestamps are supplied metadata, not authenticated
identities.

Approval changes only review status and metadata. It does not verify the claim,
write shared memory, or make the candidate available to project reconstruction.
The queue is backed by `InMemoryCaptureRepository`; all queue state is lost when
the process exits. It is a testable prototype repository, not durable storage.

## Capability 1 and 2 integration seam

Capture reuses Capability 1's `EvidenceSource`, `EvidenceType`, and
`VerificationStatus`. `evidence_sources_for(candidate, target_project=...)`
maps the capture source reference to a Capability 1 `EvidenceType.OTHER`
reference and retains any additional evidence links. It requires the candidate
project to match the explicit target project and accepts only candidates whose
review status is `approved`. The project match is a domain association guard,
not authentication; callers still need trusted authorization scope before
writing. This mapping is a conversion helper only; it does not create or
persist a `KnowledgeBundle` or change the candidate's unverified status.

The mapping keeps the capture source type in the locator, but Capability 1 has
no dedicated evidence type for a supplied summary/report. Its `EvidenceSource`
also has no source-occurrence timestamp; `EvidenceRecord.captured_at` is the
time Celestin captured the reference and must not be overloaded with the source
timestamp. A shared contract should decide whether to extend those fields or
retain typed source metadata alongside the evidence reference.

An eventual authorized adapter should expose only approved candidates to
Capability 1, create a `KnowledgeRecord` with `verification_status=unverified`,
and preserve every source/evidence reference. Capability 1 currently has no
knowledge types specifically for incomplete work or blockers; the shared-memory
owner must decide whether to extend `KnowledgeType` or how to map those
categories without losing meaning. Candidate approval must remain distinct from
verification. Rejected and pending candidates must not be included as accepted
records. Capability 2 currently reads only supplied `KnowledgeBundle` values;
it has no review-queue reader and should receive only approved, explicitly
mapped records through a future authorized read interface.

Before persistent integration, owners must agree on a project-authorized
candidate list/read contract, atomic idempotent upsert semantics, category
mapping, a way to retain conflict-group links (Capability 1 currently has no
explicit conflict relation), preservation of edits and review state, and which
actor identity is trusted for review metadata. This prototype intentionally
does not define a database schema, hosted authorization path, API, or MCP tool.
