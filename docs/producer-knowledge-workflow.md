# Producer → Knowledge workflow (internal contract v1)

**Status:** implemented as an internal, project-scoped PostgreSQL application
path. It is not an external producer schema, a trusted telemetry integration,
or a new MCP tool. No production database migration has been applied.

## Contract and identity

`orbit.capture.producer_contract.ProducerDelivery` is Celestin's versioned
internal input. It carries project, producer, source namespace, stable delivery
ID, payload revision ID, source kind/ID/revision/time, and an ordered tuple of
typed occurrences. Each occurrence carries its category, claim, source time,
and explicit evidence references; typed conflict endpoints identify producer,
candidate, and revision. Every occurrence must have evidence. The v1 hash
preimage is the full contract document serialized using RFC 8785 JCS and
SHA-256 (`celestin-producer-delivery-v1+jcs-rfc8785+sha256`). Arrays remain
ordered; duplicate occurrences are retained. No upstream producer is claimed
to emit this contract.

There are three separate identities:

1. A delivery is keyed within workspace/project, producer, source namespace,
   and delivery ID. The first successful receipt binds that key to one v1
   payload hash and payload revision ID.
2. Capture derives candidate IDs from the project, category, normalized claim,
   and a namespace derived from the registered producer/source namespace.
   PostgreSQL assigns the next immutable candidate revision under a row lock.
3. Approved conversion derives a stable Knowledge ID from the scoped producer,
   candidate, exact candidate revision, conversion hash profile, and conversion
   payload hash. This ID is not the receipt or candidate ID.

An exact delivery retry returns the persisted receipt and does not make a new
revision. The same delivery key with any different canonical payload, including
a different revision ID, fails with `delivery_id_payload_conflict`. A
transaction failure rolls back receipt, candidate, evidence association, and
occurrence writes together; the caller may retry the same delivery. The
internal application checks producer and namespace values against its trusted
per-project configuration and inserts their registry rows in the same request
transaction. Direct low-level workflow calls require those registry rows to
exist. This configuration binding does not authenticate an external producer.

## Review and conversion

Delivery first runs typed validation and Capture's sensitive-content checks,
then persists a durable receipt, Capture state snapshot, immutable candidate
revision, evidence references, occurrence links, and typed conflict
declarations in one request transaction. Missing registry entries, invalid
timestamps, incomplete evidence, unresolved conflicts, and Capture suppression
are explicit failures. Conflict endpoints must resolve within the same
workspace/project and producer scope; they are not inferred from text.

Only a human with `candidate:approve` can approve or reject a revision. A
submitter cannot approve that revision. Review events are append-only. Approval
means that a reviewer permitted conversion of this exact immutable revision;
it does not assert that the claim is true. Converted Knowledge remains
`unverified`, with unresolved evidence references and producer provenance
preserved. Repeated conversion returns the prior conversion ledger result. If a
failure occurs after the Evidence store write but before the ledger commits, the
outer request transaction rolls the Evidence write back and a retry can
complete. A review revocation prevents a new conversion but does not delete
existing Knowledge.

## Persistence and authorization

Migration `0010_producer_knowledge_workflow.sql` adds the durable delivery
receipt, immutable Capture revision snapshot, delivery-to-revision association,
and a Knowledge full-text index. Existing Evidence and Knowledge tables and
their `PostgresEvidenceLinkedMemoryStore` remain the only Evidence store. The
new tables use forced row-level security bound to the existing
`session_user`-to-project mapping. Migration 0010 grants the project runtime
login only the reads/writes needed for the workflow; it adds no delete,
truncate, trigger, or reference privileges. Hosted readiness checks this
grant matrix and the added RLS policies. The existing authorization reader,
administrator, and public MCP tool set are unchanged.

The application service requires a trusted local project resolution, an
explicit local-to-hosted project mapping, configured producer and source
namespace bindings, and an injected `HostedRequestBoundary`. The authenticated
request resolver still checks workspace membership/service grant and the
required `write`, `candidate:approve`, `memory:convert`, or `memory:read` action
before opening the project transaction. Conversion additionally requires the
existing Evidence store's `write` permission plus `memory:convert`. The
application is not registered as an MCP tool.
Callers must not pass caller-controlled project or producer identity as proof
of authorization.

## Knowledge reads and retrieval

`read_knowledge()` returns the existing typed `KnowledgeReadResult` boundary.
Empty success, failed read, and scope mismatch remain separate. Record issues,
Evidence associations, and provenance are returned by the same Evidence store.
Coverage is `REPORTED_COMPLETE` only for the current unpaginated scoped store
read and carries the existing limitation that this completeness claim was not
independently validated.

Retrieval searches current Knowledge claims using PostgreSQL FTS and joins hits
back to the exact Knowledge IDs in the typed read. An absent or mismatched
search ID is excluded with a reason; retrieval IDs are prefixed
`knowledge:<knowledge_id>` and are never presumed to equal Knowledge IDs.
Search failure, non-successful read, and project mismatch do not produce a
context bundle. The retrieval `ContextBundle` remains a projection; it is not
authoritative Knowledge and is not composed with reconstructed project state.

## Migration recovery and limits

Migration 0010 is additive and transactional under the existing migration
runner. The runner has no automatic downgrade API. Recovery is forward-safe:
if application rollout is reverted, leave the additive schema and immutable
receipts in place and run the previously deployed application against its
supported paths; do not drop tables or rewrite receipts. Correct a failed or
incomplete rollout with a reviewed forward migration after checking the
`celestin_schema_migrations` ledger and the exact migration checksum. Reapply
the same packaged migration set to verify upgrade/re-upgrade idempotency. No
migration was run against a shared or production database in this work.

This internal contract does not authenticate an external producer, administer
trusted binding configuration, or attest evidence truth.
It does not make the local SQLite Capture repository durable. The current local
stdio/MCP tools are unchanged, and this workflow is not wired as a public MCP
operation. Live PostgreSQL behavior and deployment role grants remain subject
to the opt-in disposable-database suite.
