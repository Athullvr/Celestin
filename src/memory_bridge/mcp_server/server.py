"""MCP server exposing project-memory operations."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory-bridge")


@mcp.tool()
def ping() -> str:
    """Confirm that the Memory Bridge MCP server is responding."""
    return "MCP Memory Bridge is running."


def main() -> None:
    """Run the server over stdio for local MCP clients."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
