# MCP Memory Bridge

MCP server for shared, searchable project memory.

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
memory-bridge
```

For an MCP client that launches local processes, configure the command as
`memory-bridge` (or use the environment's absolute path to `.venv\Scripts\memory-bridge.exe`).
The server exposes `ingest_chat_message`, `save_decision`,
`search_chat_history`, `retrieve_context`, and `ping`.

### Inspect and invoke the MCP tools

Connect an MCP-compatible client over stdio using this command configuration:

```json
{
  "mcpServers": {
    "memory-bridge": {
      "command": "memory-bridge",
      "args": []
    }
  }
}
```

The client should discover the four memory tools through MCP `tools/list` and
invoke them through `tools/call`. For example, call
`ingest_chat_message` with `{"project":"demo","conversation_id":"conv-1","role":"user","content":"We chose Python."}`, then call `save_decision` with
`{"project":"demo","key":"runtime","value":"Python","source_message_id":"mock-message-001"}`.
The current services return clearly marked sample IDs and do not persist data;
search and retrieval return illustrative fixtures rather than searching those
messages. The token counter in this mock phase is a UTF-8 byte estimate, and
`retrieve_context` accepts budgets from 1 through 20,000.

Run the contract tests from the repository root with:

```powershell
python -m unittest discover -s tests -v
```
