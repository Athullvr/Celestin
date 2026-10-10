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
The server currently provides a `ping` tool for a basic health check.
