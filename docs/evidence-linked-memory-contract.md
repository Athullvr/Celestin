# Evidence-linked knowledge storage contract

**Status:** Design proposal for team agreement. This document does not approve a
schema change or implement a persistence adapter. It is based on the seven
requirements shared for the Resurrection Layer; the detailed domain contract
was not present in this checkout when this review was written. Reconcile the
field mapping against that contract before implementation.

## Current Celestin fit

The hosted baseline in `src/orbit/postgres/migrations/0001_hosted_baseline.sql`
stores canonical memory in `project_memory` with a generated database ID,
`workspace_id`, `project_id`, `key`, `value`, decision `status`, one nullable
`source_message_id`, creation/update timestamps, and archive/retention fields.
It has `UNIQUE (project_id, key)` and a same-project source-message foreign key.
Migration `0002_user_status.sql` adds fail-closed user status.

The current `MemoryStore` protocol has message insert, decision save/upsert,
and decision-status update methods. `PostgresMemoryStore.save_decision()`
upserts by `(project_id, key)` and stores one message reference. Neither the
protocol nor this adapter carries candidate identity, structured capture
provenance, multiple typed evidence references, or conflict relationships.
The current decision `status` (`draft`, `approved`, `deprecated`) is not a
verification state.

Accordingly, none of the four requirements below is fully implemented by the
current persistence contract or hosted baseline. Keep the existing `key` as a
domain decision key; do not overload it with candidate identity.

## Recommended semantics for team agreement

### 1. Candidate identity

Treat a candidate ID as the stable identity of one Resurrection Layer
conversion candidate, not as a logical-claim fingerprint and not as a source
event ID. One source event may produce multiple candidates, and separate
candidates may express the same logical claim while carrying different
evidence, uncertainty, or review history. A normalized claim fingerprint can
support later duplicate analysis, but must not be the idempotency key.

Recommended uniqueness is `(project_id, producer_id, candidate_id)` because
candidate IDs are commonly local to the producer that issued them. If the
Resurrection contract guarantees that `candidate_id` is globally unique across
all producers within a project, the team may instead use the requested
`(project_id, candidate_id)` key and retain `producer_id` as provenance. Confirm
that guarantee before choosing the smaller key.

### 2. Idempotency and immutable capture

For a given candidate identity, an identical canonical capture payload returns
the existing knowledge-record ID and the existing evidence-association IDs.
Do not generate replacements on retry.

Compare the complete immutable capture payload, including content, provenance
version, source metadata, uncertainty, conflict declarations, occurrence
timestamps, and review provenance. Exclude only adapter-generated IDs and
server-generated persistence timestamps. A retry with changed content or
reviewed provenance returns a typed conflict and leaves the stored record and
links unchanged. It must not silently upsert over reviewed data. A revised
candidate should use a new candidate identity or a separately agreed explicit
revision operation.

The adapter should use deterministic canonical serialization and a digest for
efficient comparison, while retaining the full payload for equality checks
and reconstruction. A digest alone should not be the only retained provenance.

### 3. Provenance version

Include a positive integer `provenance_version` in the capture envelope. This
versions the serialized provenance shape and its interpretation; it is not a
knowledge-record revision, approval state, or verification result. Readers
must preserve supported versions and fail clearly on an unsupported version
rather than dropping unknown fields. Any format conversion must be an explicit
versioned adapter/migration with round-trip tests.

### 4. Typed evidence references

Represent evidence as typed references, not as `OTHER` with a packed locator.
Each reference should preserve, where applicable:

- evidence/source type and stable source ID;
- locator as its own field;
- source revision;
- occurrence time;
- optional content hash; and
- source-specific metadata needed to reconstruct the domain reference.

Keep `source_id`, `locator`, and `revision` distinct. Preserve the occurrence
instant and define whether exact original timestamp text/offset is required in
addition to a normalized database `TIMESTAMPTZ`. For internal chat-message
evidence, enforce the same-project foreign key. For external evidence, retain a
typed source identity and validate project scope at the application boundary;
do not claim a relational FK to a source system Celestin does not own.

An evidence-association ID must be stable across identical retries. Its
uniqueness key should be based on the knowledge record and a canonical typed
evidence identity, not only the display locator.

### 5. Conflict relationships and resolution history

Recommended default: a conflict is an undirected relationship between two
candidate identities within one project. Persist the pair in canonical order
and enforce uniqueness so reversing the endpoints cannot create a duplicate.
Reject self-links. Preserve the conflict as unresolved unless an explicit,
authorized resolution operation is invoked; capture/conversion must never
resolve it automatically.

A reference to a candidate that has not yet been converted should remain a
typed pending candidate identity, scoped to the same project/producer namespace.
When the other candidate is converted, the relationship can be linked to its
knowledge record without replacing the original candidate reference. The
Resurrection contract must confirm that candidate identities are available
before conversion; otherwise pending references need an explicit registry
design.

Resolution should append an auditable resolution event (outcome, occurrence
time, reviewer/checker provenance, and any rationale) while retaining the
original edge and capture payload. Do not delete or rewrite the original
conflict evidence. The team must confirm whether conflicts are always symmetric
and define allowed resolution outcomes before schema design.

### 6. Atomicity and concurrent retries

Expose one persistence operation for capturing a knowledge candidate and its
provenance/evidence/conflict associations. It must create or reuse the
knowledge record and create/reuse all applicable links in one PostgreSQL
transaction. Any failed validation, evidence insert, or conflict-link insert
rolls back the entire capture.

Use database uniqueness constraints as the concurrency arbiter. When concurrent
requests claim the same candidate identity, one inserts; the other waits,
loads the committed row, compares the canonical payload, and either returns
the same IDs or raises the changed-payload conflict. Unique evidence and
conflict keys prevent duplicate associations. Define bounded retry behavior
for serialization failures/deadlocks; never convert those failures into a
successful result.

The current `PostgresMemoryStore` methods open their own connection contexts.
They cannot be composed as independent calls to guarantee one transaction for
this multi-record capture. The future operation must own one transaction or
accept a transaction-bound storage session.

### 7. Authorization and reviewer provenance

The application boundary supplies the trusted, already-authorized project
scope. A project string or reviewer/checker label supplied by the caller is not
authentication. Keep reviewer identity as provenance exactly as the domain
contract defines it; do not substitute the authenticated `celestin_users`
identity or claim the label has been authenticated.

When hosted identity authorization is integrated, project authorization and
the capture operation must use the same request transaction/connection to
avoid a check-then-write gap. Approval and verification are separate concepts:
the existing decision `status` must not imply that a claim was verified, and a
verification outcome must not silently approve a decision.

## Mapping to a future PostgreSQL migration

Do not edit migrations `0001_hosted_baseline.sql` or `0002_user_status.sql`.
After the domain contract and choices above are approved, the persistence owner
should design an additive migration. At minimum it will need to support:

1. A versioned, lossless capture-provenance payload and candidate identity on
   the knowledge record (with a uniqueness constraint for the agreed scope).
2. Normalized typed evidence associations with stable IDs and uniqueness keys.
3. Queryable, project-scoped conflict identities/edges that can remain pending
   until a candidate is converted, plus append-only resolution history if
   resolutions are included in the first release.
4. Appropriate workspace/project composite foreign keys and indexes, plus a
   clear transaction-bound persistence method.

Existing records must remain readable with absent provenance during an
additive rollout. Do not synthesize candidate IDs or reviewer identities for
legacy decisions. The migration and adapter should be tested with duplicate
requests, payload mismatch, partial-link failure/rollback, concurrent inserts,
pending conflict conversion, and round-trip serialization of every domain
field.

## Decisions to ratify before implementation

1. Are candidate IDs unique only per producer, or globally unique within a
   project? This determines the unique key.
2. Which fields define identical capture payloads, and what operation creates a
   revised candidate after a mismatch?
3. What is the provenance-version compatibility policy?
4. What evidence types are in the current domain contract, and which ownable
   source types have relational records in Celestin?
5. Are conflict links symmetric? How are pending endpoints represented, and
   which explicit resolution outcomes/events are supported?
6. Which actor/time fields are reviewer provenance versus authenticated audit
   fields? Approval and verification must remain distinct.
7. Must timestamps round-trip the original offset/text or only their instant?

Once these are agreed against the actual Resurrection Layer contract, the
persistence owner can map them into an additive PostgreSQL migration and a
transactional storage operation without changing the Resurrection Layer.
