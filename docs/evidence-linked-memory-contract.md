# Evidence-linked project memory: domain contract

## Status

This is a storage-neutral domain and service prototype. It is **not wired to
SQLite, PostgreSQL, an MCP tool, or a production authorization request path**.
The current `MemoryStore` port supports messages and decisions only. No evidence
schema or adapter contract has been approved, so this change deliberately adds
no migration and changes no existing persistence or MCP behavior.

The service accepts an `AuthorizedProject` produced by Celestin's existing
authorization boundary. It does not authorize caller-supplied project strings
or replace hosted scope checks. A future application adapter must obtain the
authorized scope before calling it.

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

Conflicting claims remain separate records. Supersession creates a new record
and asks the persistence adapter to mark the previous record as superseded in
the same atomic operation. It does not delete the old claim or its evidence.
The service does not choose a source of truth by timestamp; that requires
project-specific authority policy and evidence review.

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
