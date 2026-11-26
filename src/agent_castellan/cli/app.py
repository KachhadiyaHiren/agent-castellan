"""Typer application with lazy registration of every command module."""

from __future__ import annotations

import importlib

import typer

app = typer.Typer(
    name="castellan",
    help="Least-privilege permissions for multi-agent AI systems.",
    no_args_is_help=True,
    add_completion=False,
)

# (module path, command name, one-line help used until the module is implemented)
COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("agent_castellan.cli.check", "check", "Check one call against a policy."),
    ("agent_castellan.cli.explain", "explain", "Explain why a call got its decision."),
    ("agent_castellan.cli.test", "test", "Run policy test files."),
    ("agent_castellan.cli.lint", "lint", "Lint a policy."),
    ("agent_castellan.cli.audit", "audit", "Verify and tail audit logs."),
    ("agent_castellan.cli.approve", "approve", "List, accept and reject approvals."),
    ("agent_castellan.integrations.mcp_proxy", "mcp-proxy", "Run the policy-enforcing MCP proxy."),
)


def _placeholder(name: str, help_text: str) -> None:
    @app.command(
        name,
        help=f"{help_text} (not implemented yet)",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def _not_implemented() -> None:
        typer.echo(f"castellan {name}: not implemented yet")

    del _not_implemented


def _register_all() -> None:
    for module_path, name, help_text in COMMANDS:
        try:
            module = importlib.import_module(module_path)
            module.register(app)
        except (ImportError, NotImplementedError):
            # Missing optional extra (for example `[mcp]`) or command not built yet.
            _placeholder(name, help_text)


_register_all()


def main() -> None:
    """Console-script entry point."""
    app()
