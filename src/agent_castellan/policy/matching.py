"""Tool-glob and agent-role matching (WS1)."""

from __future__ import annotations

from collections.abc import Sequence


def match_tool(patterns: Sequence[str], tool: str) -> bool:
    """Say whether a normalized tool name matches any glob pattern."""
    raise NotImplementedError


def match_agent(roles: Sequence[str], role: str) -> bool:
    """Say whether a role is selected by a rule's `agents` list."""
    raise NotImplementedError
