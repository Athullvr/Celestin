# Local project-context application boundary

`orbit.project_state.ProjectContextService` composes an explicit local project
selection with the existing read-only Git reconstruction. The configured
`LocalProjectResolver` is the only source of the repository root. Reconstruction
returns the resolved Git commit SHA and reads that commit's tracked blobs; it
does not modify or inspect the working tree for project-state findings.

The result keeps three kinds of information separate:

- `project_id` is the local ID selected through `LocalProjectResolver`.
- `knowledge_read` is the optional typed `KnowledgeReadResult`; its
  `project_id` is the Knowledge scope ID and is not assumed to equal the local
  ID.
- `reconstruction` is the `ProjectStateSnapshot`; it is not Retrieval's
  `ContextBundle` and is not a ranking or prompt-packing result.

If no reader is configured, `knowledge_read` is `None`,
`knowledge_read_outcome` and `knowledge_coverage` are `None`, and the result
states that Knowledge was not read. A reader that ran should return
`KnowledgeReadResult` with its actual scope, outcome, coverage, record issues,
and limitations. Failed or scope-mismatched results contribute no records to
reconstruction. Partial or unknown coverage is not treated as absence,
deletion, or conflict resolution. Reported completeness remains a source claim,
not verified completeness.

## Explicit missing dependency

`ProjectKnowledgeReader` is only an internal protocol. No production local
implementation is connected. A future implementation must accept the resolved
`LocalProjectBinding`, use an explicitly configured and approved mapping to the
Knowledge project scope, enforce the applicable local read policy, and return a
typed result for that Knowledge scope. The application does not equate local,
hosted, Retrieval, candidate, or Knowledge identifiers and does not provide a
fallback lookup through Retrieval.

The Git revision and Knowledge read are independent snapshots. No transaction
or snapshot token binds them. The current boundary also does not wire Capture,
MCP tools, persistence, hosted authorization, synchronization, or retrieval
context assembly. This is an application seam for focused integration work,
not a claim that those product paths are available.
