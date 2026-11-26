"""Tool-glob and agent matching."""

from __future__ import annotations

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.policy.matching import match_agent, match_tool, tool_glob_regex


@pytest.mark.parametrize(
    ("patterns", "tool", "expected"),
    [
        (["*"], "fs.read", True),
        (["*"], "mcp:files/a.b", True),
        ([" * "], "x.y.z", True),
        (["fs.read"], "fs.read", True),
        (["fs.read"], "fs.write", False),
        (["FS.Read"], "fs.read", True),  # patterns are lower-cased too
        (["fs.*"], "fs.read", True),
        (["fs.*"], "fs.a.b", False),  # * never crosses a dot
        (["fs.*"], "fs", False),
        (["fs.**"], "fs.a.b", True),
        (["**"], "a.b.c", True),
        (["*.read"], "fs.read", True),
        (["*.read"], "a.b.read", False),
        (["pay*.charge"], "payments.charge", True),
        (["mcp:files/*"], "mcp:files/read_file", True),
        (["mcp:*/read_file"], "mcp:files/read_file", True),
        (["mcp:files/*"], "mcp:other/read_file", False),
        (["fs.read", "web.*"], "web.fetch", True),
        (["fs.read", "web.*"], "db.query", False),
        (["fs.re?d"], "fs.read", False),  # ? is literal
        (["fs.re?d"], "fs.re?d", True),
        (["a+b"], "a+b", True),  # regex metacharacters are literal
        (["a+b"], "aab", False),
        (["fs.(x)"], "fs.(x)", True),
    ],
)
def test_match_tool(patterns: list[str], tool: str, expected: bool) -> None:
    assert match_tool(patterns, tool) is expected


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_tool_pattern_is_an_error(bad: str) -> None:
    with pytest.raises(PolicyError):
        tool_glob_regex(bad)
    with pytest.raises(PolicyError):
        match_tool([bad], "x")


@pytest.mark.parametrize(
    ("roles", "role", "expected"),
    [
        (["*"], "coder", True),
        (["coder"], "coder", True),
        (["researcher", "coder"], "coder", True),
        (["researcher"], "coder", False),
        (["Coder"], "coder", False),  # role names are case-sensitive
        ([], "coder", False),
    ],
)
def test_match_agent(roles: list[str], role: str, expected: bool) -> None:
    assert match_agent(roles, role) is expected
