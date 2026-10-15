# Evidence-linked project memory: domain contract

## Status

This is a storage-neutral domain and service prototype. It is **not wired to
SQLite, PostgreSQL, an MCP tool, or a production authorization request path**.
The current `MemoryStore` port supports messages and decisions only. No evidence
schema or adapter contract has been approved, so this change deliberately adds
no migration and changes no existing persistence or MCP behavior.

The service accepts an `AuthorizedProject` as a project/action selector and
re-authorizes each operation through an injected `ProjectAuthorizer`. The
trusted service factory fixes the principal on the service instance; the
principal carried by a caller-supplied scope is not used for authorization.
This is a domain guard, not transport authentication: untrusted callers must
not be allowed to construct a service with a permissive authorizer or choose
its principal. No Resurrection Layer operation is currently exposed through
MCP. Hosted integration must supply the trusted principal and authorizer at
the application boundary and continue checking membership on every request.

## Domain records

`KnowledgeRecord` stores a concise claim, project scope, knowledge type,
timestamps, verification status, lifecycle status, and explicit predecessor /
successor IDs. `EvidenceRecord` stores a stable ID and project-scoped reference
to a message, repository file, commit, test result, document, or other source.
It records a locator, optional revision and content hash, capture time,
resolution state, verification status, and optional check metadata. Source
contents are not copied into the evidence record.

Verification (`unverified`, `verified`, `stale`, `conflicting`) is separate from
lifecycle (`current`, `superseded`, `archived`). New claims and evidence begin
unverified. Setting a checked status requires an explicit `checked_by` value;
this records the caller's check and does not prove that the check occurred.
The service never marks evidence verified automatically. A source that a
resolver cannot check remains `unresolved`; a source the resolver confirms is
missing is rejected before persistence. Readback re-resolves source
availability, but availability alone does not establish freshness or truth.
The service rejects evidence rows returned by a storage adapter when their
project differs from the authorized read scope. Project-state reconstruction
also omits out-of-scope evidence from a supplied bundle and reports that
limitation, so a faulty read adapter cannot expose a foreign source reference
through the snapshot.

Conflicting claims remain separate records. Supersession creates a new record
and asks the persistence adapter to mark the previous record as superseded in
the same atomic operation. It does not delete the old claim or its evidence.
The service does not choose a source of truth by timestamp; that requires
project-specific authority policy and evidence review.

## Capability 3 conversion contract (domain prototype)

`KnowledgeRecord.capture_provenance` is an optional storage-neutral
`CaptureKnowledgeProvenance` value. `capture_provenance_for(candidate,
target_project=...)` creates it only for an approved, unverified candidate in
the matching project. This is a domain project check, not authentication. The
normal `KnowledgeRecord.verification_status` remains `unverified` at creation;
reviewer labels are untrusted provenance and are never copied into
`checked_by`.

| Capability 3 field | Capability 1 representation | Contract semantics |
| --- | --- | --- |
| Candidate ID and project | `capture_provenance.candidate_id/project_id`; `KnowledgeRecord.project` is the destination scope | Candidate ID remains the stable origin key. C1 validates provenance project against authorized scope. A durable adapter should enforce unique `(project, candidate_id)` conversion and idempotent replay. |
| Claim and category | `KnowledgeRecord.claim`, `KnowledgeRecord.knowledge_type`, and provenance `original_claim/category` | Current edited claim is authoritative as `claim`; original text is retained when present. Supported category mappings are decision→decision, discovery→discovery, bug fix→bug fix, completed work→completed work, constraint→requirement, and implementation detail→implementation finding. Incomplete work and blocker have no agreed C1 type and are rejected by the mapping helper. Raw category remains in provenance. |
| Source IDs, source type, locator, revision, occurrence time | Evidence associations are `EvidenceRecord` rows; raw typed origins are `capture_provenance.source_references` | Evidence rows remain authoritative for C1 resolution/verification state. Capture source references preserve original source type and `occurred_at`; their source IDs, locators, and revisions link them to mapped `EvidenceType.OTHER` rows. `EvidenceRecord.captured_at` and `KnowledgeRecord.created_at` are C1 persistence time, distinct from source occurrence and candidate/review timestamps. C2 reports original locator/hash and recorded resolution status. |
| Evidence relationships and IDs | Store associates each `EvidenceRecord` with `knowledge_id`; reconstruction exposes `knowledge_record_id` and `evidence_record_id` | The existing store association is authoritative. Capability 2 carries both generated C1 identifiers in its output. |
| Review status and reviewer provenance | `capture_provenance.review_status`, `reviewed_by`, `reviewed_at`, `review_note` | Only `approved` provenance is accepted. These labels describe a review assertion; they are not authenticated identities and do not imply verification. Candidate creation/update times and original claim are retained in this value too. |
| Verification and checker provenance | `KnowledgeRecord.verification_status`, `checked_by`, `checked_at`, `check_note`; candidate status is retained separately as `candidate_verification_status` | Conversion requires candidate status `unverified` and creates C1 knowledge unverified. A later explicit C1 verification assertion owns the destination checker fields. The C1 service does not authenticate the supplied checker label. C2 carries those assertion fields separately from its own evidence classification. |
| Uncertainty | `capture_provenance.certainty` | Preserved verbatim (`uncertain` or `unqualified`); it is not a confidence score and does not change verification. |
| Conflicts | `capture_provenance.conflicts_with` | Candidate IDs remain linkable across records. No semantic conflict resolution occurs. The adapter must support querying by candidate ID or the conflict IDs are only retained, not conveniently traversable. |
| Lifecycle/supersession | Existing `KnowledgeRecord.lifecycle_status`, `supersedes_id`, `superseded_by_id` | These remain authoritative and separate from capture review. Superseded records retain their own capture provenance and evidence. Capability 3 candidates do not currently express lifecycle transitions. |

This is a domain contract only. PostgreSQL/SQLite adapters must agree on a
representation that round-trips `capture_provenance`, preserves source-to-
evidence associations, knowledge/evidence record IDs, checker metadata,
lifecycle links, and candidate idempotency before persistence integration. No
database schema is implied by these dataclasses. A storage
adapter that cannot preserve the optional value must reject/flag the conversion
instead of silently dropping it.

## Storage port required for integration

`EvidenceLinkedMemoryStore` is the minimal storage-neutral service contract in
`src/orbit/evidence/service.py`. An adapter must provide:

- Atomic creation of one knowledge record with its initial evidence records.
- Project-scoped retrieval of a record and all associated evidence.
- Project-scoped evidence association with idempotency for a repeated source
  type, source ID, locator, revision, and content hash.
- Explicit knowledge and evidence verification updates.
- Atomic supersession that preserves the previous record and its evidence.
- Project-scoped identifier checks and transaction/error behavior consistent
  with the existing adapter.

The persistence owner must agree how this relation maps to SQLite and the
hosted PostgreSQL schema before adapters or migrations are added. In
particular, external source references need a stable format and the hosted
adapter must bind every evidence row to its workspace and project. The
existing decision `source_message_id` can remain useful as a legacy one-source
link, but it cannot represent multiple sources, independent verification, or
supersession history. Reusing decision upsert behavior would overwrite history
and is not suitable.

`EvidenceReferenceResolver` is a second integration seam. The current storage
port has no source-read method, so an adapter still needs a project-scoped way
to resolve Celestin message IDs. Repository files, commits, tests, and
documents need their own authorized resolver or trusted integration. Until
those adapters exist, this service is not a usable persistence feature.

## Deliberate non-goals for this stage

- No SQLite or PostgreSQL DDL, migration, or adapter implementation.
- No automatic source scanning, source-content copying, or claim extraction.
- No automatic conflict resolution, freshness inference, or decision approval.
- No new MCP tool and no change to existing retrieval contracts.
- No claim that a test result or commit proves a feature works.

The deterministic unit tests use a test-only fake store. They exercise domain
validation, status distinctions, scope propagation, idempotent port semantics,
and failure handling; they do not validate persistence, cross-process
durability, PostgreSQL behavior, or hosted authorization.
