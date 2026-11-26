"""Stdio MCP proxy that enforces policy on `tools/call` (WS5)."""

from __future__ import annotations

import typer


def register(app: typer.Typer) -> None:
    """Register the `mcp-proxy` command on the CLI app."""
    raise NotImplementedError
