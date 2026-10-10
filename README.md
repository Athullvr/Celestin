# Orbit — Persistent Memory for AI Agents

An MCP-powered persistent memory system for AI agents and coding assistants.

## Local setup

Requires Python 3.10 or newer. From the repository root, install the project and
its dependencies in editable mode:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run the server over stdio:

```powershell
orbit
```

For Codex CLI, register the local stdio server from the repository environment:

```powershell
codex mcp add orbit --env 'MEMORY_BRIDGE_DB_PATH=C:\path\to\memory_bridge.db' -- orbit
codex mcp list
```

Replace the example database path with an absolute writable path. The server
must be installed in the environment where `orbit` resolves. If needed, use the
absolute path to `.venv\Scripts\orbit.exe` in place of `orbit`. Codex stores
this server in the user's MCP configuration; restart the Codex client after
registration if it is already running. If you previously registered the old
server, remove it with `codex mcp remove memory-bridge` before registering
Orbit. To remove Orbit later, run `codex mcp remove orbit`. Quote the absolute
executable path if it contains spaces.

Other local MCP clients can launch `orbit` directly (or use the environment's
absolute path to `.venv\Scripts\orbit.exe`).
The server exposes `ingest_chat_message`, `save_decision`,
`search_chat_history`, `retrieve_context`, and `ping`.

`ingest_chat_message` and `save_decision` persist through the SQLite
repositories. Search and context retrieval use the SQLite FTS5 indexes and the
retrieval service. The database is created at `data/memory_bridge.db` by
default; set `MEMORY_BRIDGE_DB_PATH` before launching the server to choose
another path. Saved decisions start in `draft` status; context retrieval gives
approved decisions priority and excludes drafts and deprecated decisions.

### Inspect and invoke the MCP tools

Connect another MCP-compatible client over stdio using this command configuration:

```json
{
  "mcpServers": {
    "orbit": {
      "command": "orbit",
      "args": []
    }
  }
}
```

The client should discover the four memory tools and the `ping` health check
through MCP `tools/list` and invoke them through `tools/call`. For example, call
`ingest_chat_message` with
`{"project":"demo","conversation_id":"conv-1","role":"user","content":"We chose Python."}`.
Use its returned `message_id` as `source_message_id` when calling
`save_decision`. Search reads persisted messages and returns the matching
message ID, conversation ID, timestamp, and relevance score. Context retrieval
combines eligible decisions and messages, returning source traceability and
the retrieval service's token counter metadata. The current counter is a
UTF-8 byte estimate, and `retrieve_context` accepts budgets from 1 through
20,000.

Run the contract tests from the repository root with:

```powershell
python -m unittest discover -s tests -v
```
