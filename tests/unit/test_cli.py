"""The CLI lists every command group even before they are implemented."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agent_castellan.cli.app import app

runner = CliRunner()
COMMANDS = ["check", "explain", "test", "lint", "audit", "approve", "mcp-proxy"]


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in COMMANDS:
        assert name in result.output


@pytest.mark.parametrize("name", COMMANDS)
def test_unimplemented_command_says_so(name: str) -> None:
    result = runner.invoke(app, [name, "--anything"])
    assert result.exit_code == 0
    assert "not implemented yet" in result.output
