"""Tool-glob and agent-role matching (WS1)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from functools import lru_cache

from ..errors import PolicyError


def tool_glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a tool glob: `*` skips dots, `**` matches anything; case-insensitive input."""
    if not pattern or not pattern.strip():
        raise PolicyError("tool pattern must not be empty")
    pattern = pattern.strip().lower()
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^.]*")
        else:
            out.append(re.escape(pattern[i]))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def compile_tool_matcher(patterns: Sequence[str]) -> Callable[[str], bool]:
    """Compile tool globs once into a predicate over normalized tool names."""
    stripped = [p.strip() for p in patterns]
    if "*" in stripped:
        return lambda _tool: True
    regexes = [tool_glob_regex(p) for p in stripped]
    if len(regexes) == 1:
        single = regexes[0]
        return lambda tool: single.fullmatch(tool) is not None
    combined = re.compile("|".join(f"(?:{r.pattern})" for r in regexes), re.DOTALL)
    return lambda tool: combined.fullmatch(tool) is not None


@lru_cache(maxsize=512)
def _cached_matcher(patterns: tuple[str, ...]) -> Callable[[str], bool]:
    return compile_tool_matcher(patterns)


def match_tool(patterns: Sequence[str], tool: str) -> bool:
    """Say whether a normalized tool name matches any glob pattern."""
    return _cached_matcher(tuple(patterns))(tool)


def match_agent(roles: Sequence[str], role: str) -> bool:
    """Say whether a role is selected by a rule's `agents` list."""
    return "*" in roles or role in roles
