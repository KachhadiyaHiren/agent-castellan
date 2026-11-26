"""End-to-end CLI runs against the real components; skipped until those land."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.policy import loader

Invoke = Callable[..., Any]

POLICY = """\
version: 1
defaults:
  effect: deny
agents:
  coder: {}
rules:
  - id: no-secrets
    tools: ["*"]
    when:
      args.path: { glob: "**/.env*" }
    effect: deny
  - id: read-workspace
    agents: [coder]
    tools: ["fs.read"]
    when:
      args.path: { glob: "/workspace/**" }
    effect: allow
  - id: write-needs-review
    agents: [coder]
    tools: ["fs.write"]
    effect: ask
"""

TESTS = """\
policy: team.yaml
cases:
  - name: coder cannot read secrets
    agent: { role: coder, depth: 1 }
    call: { tool: fs.read, args: { path: /workspace/.env } }
    expect: deny
    expect_rule: no-secrets
  - name: coder write needs approval
    agent: { role: coder }
    call: { tool: fs.write, args: { path: /workspace/app.py } }
    expect: ask
"""

pytestmark = pytest.mark.needs_ws1


@pytest.fixture
def team(tmp_path: Path) -> Path:
    try:
        loader.load_policy_text("version: 1\n")
    except NotImplementedError:
        pytest.skip("WS1 policy loader not implemented yet")
    path = tmp_path / "team.yaml"
    path.write_text(POLICY)
    (tmp_path / "team.test.yaml").write_text(TESTS)
    return path


@pytest.mark.parametrize(
    ("tool", "args", "code"),
    [
        ("fs.read", '{"path": "/workspace/a.txt"}', 0),
        ("fs.read", '{"path": "/workspace/.env"}', 1),
        ("fs.write", '{"path": "/workspace/a.txt"}', 2),
    ],
)
def test_check_real_policy(invoke: Invoke, team: Path, tool: str, args: str, code: int) -> None:
    result = invoke("check", str(team), "--role", "coder", "--tool", tool, "--args", args)
    assert result.exit_code == code


def test_explain_real_policy(invoke: Invoke, team: Path) -> None:
    result = invoke(
        "explain", str(team), "--role", "coder", "--tool", "fs.read",
        "--args", json.dumps({"path": "/workspace/a.txt"}),
    )  # fmt: skip
    assert result.exit_code == 0
    assert "read-workspace" in result.output


def test_test_real_policy(invoke: Invoke, team: Path) -> None:
    result = invoke("test", str(team.parent / "team.test.yaml"))
    assert result.exit_code == 0
    assert "2 passed" in result.output


def test_lint_real_policy(invoke: Invoke, team: Path) -> None:
    try:
        result = invoke("lint", str(team), "--format", "json")
    except NotImplementedError:  # pragma: no cover
        pytest.skip("WS4a linter not implemented yet")
    if result.exit_code == 3 and "not implemented" in result.output:
        pytest.skip("WS4a linter not implemented yet")
    assert isinstance(json.loads(result.output), list)
