"""Tiny MCP server used by the proxy tests (stdio)."""

from __future__ import annotations

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

server = _Server("echo")


@server.tool()
def echo(text: str) -> str:
    """Echo the text back."""
    return f"echo:{text}"


@server.tool()
def delete_all(confirm: bool = False) -> str:
    """Pretend to delete everything."""
    return "deleted"


if __name__ == "__main__":
    server.run("stdio")
