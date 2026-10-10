# MCP Memory Bridge

MCP server for shared, searchable project memory. It stores chat messages and project decisions in SQLite and exposes project-scoped search and context retrieval through the official Python MCP SDK.

## Local setup

Requires Python 3.10 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run the server over stdio:

```powershell
memory-bridge
```

For an MCP client that launches local processes, configure the command as `memory-bridge` (or use the environment's absolute path to `.venv\Scripts\memory-bridge.exe`). The server exposes `ingest_chat_message`, `save_decision`, `search_chat_history`, `retrieve_context`, and `ping`.

The database is created at `data/memory_bridge.db` by default. Set `MEMORY_BRIDGE_DB_PATH` before launching the server to choose another path. Saved decisions start in `draft` status; context retrieval gives approved decisions priority and excludes drafts and deprecated decisions.

### MCP client configuration

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

The client discovers tools through MCP `tools/list` and invokes them through `tools/call`. For example, call `ingest_chat_message` with `{"project":"demo","conversation_id":"conv-1","role":"user","content":"We chose Python."}`. Use its returned `message_id` as `source_message_id` when calling `save_decision`.

Search reads persisted messages and returns message IDs, conversation IDs, timestamps, and relevance scores. Context retrieval combines eligible decisions and messages and returns source traceability and token-counter metadata. The current counter is a UTF-8 byte estimate; `retrieve_context` accepts budgets from 1 through 20,000.

### Tests

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

## DevDay Exchange resources

This project was built from the DevDay Exchange Community: Kochi template. Event guidance remains in [RULES.md](RULES.md), [AGENTS.md](AGENTS.md), and [SUBMISSION.md](SUBMISSION.md). See [AI_USAGE.md](AI_USAGE.md) and [CHANGELOG.md](CHANGELOG.md) for event documentation.

- Event: 10–11 October 2026 at JAIN University, Kochi.
- [Event and registration on Luma](https://luma.com/z10nz8gp)
