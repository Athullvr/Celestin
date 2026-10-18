# Resurrection retry and failure acceptance scenarios

**Status: PROPOSED / BLOCKED pending shared-storage owner decisions.** This is
test planning only. It does not define a storage contract, transaction boundary,
identifier rule, retry response, or conflict policy.

The current repository has storage-neutral Capture mapping helpers and an
Evidence Memory service port. Its protocol documents atomic
`create_knowledge` and `supersede_knowledge` calls, but no production adapter
implements that port. The cross-capability test bridge is test-only. Existing
fake-store idempotency and error-propagation tests do not establish production
conversion retry behavior or transaction boundaries across all conversion
associations.

| Scenario | Test setup and observations | Contract decision required before asserting outcomes |
|---|---|---|
| Identical conversion retry | Submit the same approved candidate conversion payload twice, including the same candidate identity, claim, source references, review provenance, and declared conflict references. Record the returned knowledge/evidence/link identities and persisted state after each call. | Define the identity/idempotency key and whether a retry returns the prior result, reports a duplicate, or has another explicit result. |
| Changed payload on retry | Repeat a conversion identity while changing one persisted field at a time, such as claim, source reference, review metadata, or conflict references. Inspect the resulting state and error/result. | Define canonical payload comparison and whether changed content is rejected, versioned, or handled through an explicit update operation. Do not silently assume upsert or immutable rejection. |
| Concurrent identical retries | Synchronize two conversion requests with the same identity and payload so they contend, then inspect both outcomes and the final knowledge/evidence/link set. | Define concurrency arbitration, loser response, uniqueness scope, and retryable database failure behavior. |
| Partial failure | Inject a failure between the knowledge record, evidence, and conflict association writes; inspect the returned result and all persisted records/links. Repeat at each supported failure point. | Define which writes form one atomic operation, which failures roll back, and what callers may observe after an uncertain commit. No rollback assertion is valid until the owner approves the operation boundary. |

These cases remain **BLOCKED** for production acceptance assertions until the
shared-storage owner resolves the listed decisions and exposes the approved
operation to the integration tests. Pure unit tests may still validate Capture
mapping and service-level error propagation, but they must not be reported as
production conversion or persistence integration.
