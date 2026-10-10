# Orbit remote MCP authorization design proposal

**Status:** Design proposal only. It does not enable authentication, HTTP transport, a tunnel, or remote access. The existing local stdio workflow and its client configuration remain unchanged.

## Current enforcement point and gap

The MCP handlers in `src/orbit/mcp_server/server.py` validate the `project` string and pass it to the persistence or retrieval adapter:

- `ingest_chat_message` and `save_decision` perform project-scoped writes.
- `search_chat_history` and `retrieve_context` perform project-scoped reads.
- `save_decision` resolves `source_message_id` within the requested project and treats cross-project sources as not found.

These checks isolate records relative to the requested project, but there is no authenticated principal and no mapping from a principal to permitted projects. Today, any caller that can invoke the tools can supply another project name. On a remote transport, this would permit cross-project access. A project parameter must remain a resource selector only; it must never be treated as proof of authorization.

The authorization boundary belongs in the MCP server layer, after transport authentication and before any persistence or retrieval adapter is called. The server must authorize every tool call. Data and retrieval layers should continue to enforce the supplied project predicate and may repeat policy checks if the owning members agree, but the MCP layer must not duplicate SQL or retrieval logic.

## Proposed interface

Introduce an injectable authorization dependency owned by the MCP server layer. The names below are proposals, not committed public interfaces:

```python
class ProjectAuthorizer(Protocol):
    def authorize(
        self,
        principal: AuthenticatedPrincipal,
        project: str,
        action: ProjectAction,
    ) -> AuthorizedProject: ...
```

Conceptual values:

- `AuthenticatedPrincipal`: server-verified issuer and stable subject identifier, plus tenant/workspace identity and granted scopes. Constructed only from validated credentials; never from MCP tool arguments.
- `ProjectAction`: at minimum `read` and `write`. Map `search_chat_history` and `retrieve_context` to `read`; map `ingest_chat_message` and `save_decision` to `write`.
- `AuthorizedProject`: a server-issued scope containing the canonical project identifier and principal, returned only after policy approval. Handlers pass this authorized scope or its canonical project identifier to service adapters.
- `ProjectAccessDenied`: a typed authorization failure converted by the MCP boundary into a stable, non-sensitive error. Do not reveal whether an inaccessible project exists.

The identity provider or verifier must validate signature, issuer, audience/resource, expiry, and required scopes. Authorization must use a server-side project membership source, such as an approved identity provider group mapping or project access registry. Missing, unavailable, or ambiguous membership data must fail closed. An arbitrary bearer string, shared hard-coded token, caller-supplied subject, or project-name allowlist supplied with the request is not acceptable authentication or authorization.

No membership table or project registry currently exists in the inspected database schema. Selecting and owning the membership source is a team decision. This proposal does not prescribe changes to Member 1's schema or repositories.

## Access model

1. **Authenticate each remote request.** Validate the remote client's OAuth access token or other team-approved standards-based credential before tool dispatch. Authentication failure prevents all tool execution.
2. **Authorize each operation.** Check the authenticated subject's membership for the requested project and action. Do not infer permission from tool selection, ChatGPT workspace membership, a tunnel ID, or the project argument.
3. **Deny by default.** No membership, unknown principal, unknown project, missing scope, expired credential, or policy service failure denies access.
4. **Use least privilege.** Read and write permissions are separate. A read-only client may search and retrieve but cannot ingest messages or save decisions. If project-specific roles are adopted, server-side policy maps them to actions.
5. **Preserve data-layer scoping.** Continue passing the authorized canonical project to repository and retrieval services. Source-message references must resolve within that same project. Do not trust result payloads without confirming their project matches the authorized scope.
6. **Avoid project-existence disclosure.** Return the same safe denial for an inaccessible project whether it exists or not. For a source message that is absent or belongs to another project, preserve the contract's `SOURCE_MESSAGE_NOT_FOUND` behavior.
7. **Keep stdio unchanged.** Existing local client setup remains the stdio entry point. Remote auth configuration must be isolated to a future remote adapter/transport and must not introduce a development bypass that can be reached remotely.

The public error contract currently does not define an authorization error. Before implementation, agree whether the MCP layer should expose `ACCESS_DENIED`, use a generic `PROJECT_NOT_FOUND` response for inaccessible resources, or use an equivalent standardized MCP authorization error. Transport-level authentication failures should use the selected protocol's normal unauthorized response. In all cases, do not send token claims, identity-provider errors, or membership details to the client.

## Write-operation safeguards

- `ingest_chat_message` and `save_decision` require a valid identity and explicit project write permission on every invocation.
- A denied write must fail before calling persistence; tests must verify no row or FTS entry is written.
- `save_decision` continues to create a `draft`; remote access must not imply approval. Approval remains a distinct action outside the current four-tool contract.
- Client-side confirmation prompts or tool annotations may improve user awareness, but they do not replace server authorization. Decide whether both write tools require an additional explicit confirmation in the selected client.
- Add audit events for principal ID, project ID, tool/action, outcome, and request correlation ID. Do not log conversation content, decision values, credentials, or raw tokens.
- Do not add retry behavior for writes until idempotency semantics are defined; a timeout must not silently duplicate a user operation.

## Configuration required before remote implementation

The exact variable names are to be set after selecting the identity provider and architecture. Configuration must include:

- Remote mode/transport explicitly enabled only in the approved deployment; stdio remains the default local workflow.
- OAuth resource/audience and trusted issuer or introspection/JWKS configuration, plus required read/write scopes.
- Project membership provider and tenant/workspace mapping, with a documented default-deny policy.
- Secret-manager or environment injection for client credentials, signing/introspection secrets, tunnel runtime keys, and database credentials. Never commit secrets or print them in logs.
- If using Secure MCP Tunnel: approved tunnel ID, Platform organization association, runtime key, required `Tunnels Read + Use` permission, ChatGPT workspace access, and a fixed local stdio command/working directory. Set `MEMORY_BRIDGE_DB_PATH` explicitly so the tunnel-launched process and local IDE use the same intended database.
- If using a hosted service: HTTPS termination, network policy, private persistence (not a downloadable/public SQLite file), backups, migrations, service health checks, rate limits, and operational ownership.

Do not bind the current server to an unauthenticated network address. Tunnel access alone does not satisfy the application authorization requirements above.

## Required test plan

Implement these as transport/auth integration tests using isolated test databases and test identities; do not use real conversation data.

| Case | Expected result | Persistence/retrieval assertion |
|---|---|---|
| Missing authorization credential | Unauthorized response; no tool result | No service method called |
| Invalid signature, expired token, wrong issuer/audience | Unauthorized response; safe body | No service method called |
| Valid identity without project membership | Generic access denial | No read result and no write |
| Member of project A requests search/context for project B | Generic access denial | B records never returned; service not called or only receives authorized scope |
| Member of project A tries to ingest/save to project B | Generic access denial | No new message, decision, or FTS row in either project |
| Member with read scope attempts a write | Forbidden/access denied | No persistence call |
| Authorized member reads own project | Success | Returned rows all have authorized project ID |
| Authorized member writes own project | Success when write policy/confirmation is satisfied | Only authorized project's rows and indexes change |
| Decision references another project's message ID | `SOURCE_MESSAGE_NOT_FOUND` | No decision created; response does not disclose other-project source |
| Membership provider unavailable or ambiguous | Safe denial/service-unavailable policy; fail closed | No adapter call |
| Remote write request lacks required confirmation, if team adopts confirmation | Safe denial/cancelled operation | No persistence call |
| Tool/authorization failure contains internal token, path, or provider detail | Sanitized MCP error | Neither response nor logs contain secret or conversation text |
| Existing local stdio workflow | Existing behavior and configuration continue | Local contract suite passes |

## Decisions requiring the three-person team

### Member 1 — Database and memory core

- Confirm whether projects are provisioned entities or arbitrary namespace strings and identify the canonical project identifier.
- Identify the owner and source of project membership (existing identity/group provider, a separately owned authorization service, or a future repository-backed registry). No authorization schema is present in the current SQLite migrations.
- Confirm the persistence boundary continues to enforce project predicates for all operations and source-message lookup, and agree whether repositories receive an authorized project scope or only the canonical project ID.
- Agree on safe behavior for unknown projects and cross-project source IDs without disclosing resource existence.

### Member 2 — Retrieval

- Confirm both retrieval entry points always constrain candidates and final results to the authorized canonical project, even when upstream index metadata is inconsistent.
- Confirm the retrieval adapter can accept the server-authorized project scope/canonical identifier without changing ranking or retrieval semantics.
- Confirm how authorization failures and retrieval outages are distinguished and sanitized at the MCP boundary.

### Member 3 — MCP server and integration

- Select the identity token verifier and project authorization dependency contract; define principal fields, read/write scopes, and failure codes.
- Decide where transport authentication terminates and ensure remote requests cannot bypass it. Keep the stdio client path unchanged.
- Decide whether `ingest_chat_message` and `save_decision` need client confirmation/annotations in addition to server-side write authorization.
- Approve the safe error mapping and audit fields, and add the authorization integration tests before enabling remote transport.

### Shared/team decisions

- Verify the actual ChatGPT workspace plan, custom MCP/developer-mode access, and Platform tunnel permissions. Full write-capable ChatGPT MCP support is plan/workspace-dependent and currently documented as beta.
- Choose Secure MCP Tunnel for a limited pilot versus a hosted HTTPS service for durable team availability; name the operational owner.
- Explicitly approve whether and which project memory may be sent to ChatGPT when a remote tool call returns context. Define user opt-in, approved projects, retention expectations, and prohibited data classes.
- Confirm team/project membership rules, read/write role semantics, authorization-denial error contract, and any user confirmation policy for writes.
- Confirm production configuration, secret management, backups/retention, audit access, revocation procedure, and incident response before deployment.
