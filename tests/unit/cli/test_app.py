"""The CLI lists every command and keeps placeholders for modules that cannot register."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agent_castellan.cli import app as app_mod

runner = CliRunner()
COMMANDS = ["check", "explain", "test", "lint", "audit", "approve", "mcp-proxy"]


def test_help_lists_every_command() -> None:
    result = runner.invoke(app_mod.app, ["--help"])
    assert result.exit_code == 0
    for name in COMMANDS:
        assert name in result.output


@pytest.mark.parametrize("name", ["check", "explain", "test", "lint", "audit", "approve"])
def test_cli_commands_are_registered_not_placeholders(name: str) -> None:
    result = runner.invoke(app_mod.app, [name, "--help"])
    assert result.exit_code == 0
    assert "not implemented yet" not in result.output


def test_placeholder_command_says_not_implemented() -> None:
    import typer

    scratch = typer.Typer()
    original = app_mod.app
    app_mod.app = scratch
    try:
        app_mod._placeholder("demo", "Demo command.")
    finally:
        app_mod.app = original
    result = runner.invoke(scratch, ["demo"])
    assert result.exit_code == 0
    assert "not implemented yet" in result.output
