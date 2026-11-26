"""`castellan explain` command: show the rule trace behind a decision."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..models import ToolCall
from ._common import (
    ArgsOpt,
    BehalfOpt,
    DepthOpt,
    ParentRoleOpt,
    PolicyArg,
    RoleOpt,
    ToolOpt,
    build_principal,
    decide,
    decision_line,
    exit_code_for,
    load_policy_or_exit,
    parse_args,
)


def explain(
    policy: PolicyArg,
    role: RoleOpt,
    tool: ToolOpt,
    args: ArgsOpt = "{}",
    depth: DepthOpt = 0,
    parent_role: ParentRoleOpt = None,
    on_behalf_of: BehalfOpt = None,
) -> None:
    """Print a table of every rule considered. Exit codes match `check`."""
    loaded = load_policy_or_exit(policy)
    call = ToolCall(tool=tool, args=parse_args(args))
    decision = decide(loaded, build_principal(role, depth, parent_role, on_behalf_of), call)

    console = Console(highlight=False)
    console.print(decision_line(decision), markup=False)
    table = Table(title="Rule trace")
    table.add_column("Rule")
    table.add_column("Matched")
    table.add_column("Detail")
    for step in decision.trace:
        table.add_row(step.rule_id, "yes" if step.matched else "no", step.detail)
    console.print(table)
    raise typer.Exit(exit_code_for(decision.effect))


_HELP = (
    "Show every rule considered for a call and why it matched or not.\n\n"
    "Takes the same options and exit codes as `castellan check`."
)


def register(app: typer.Typer) -> None:
    """Register the `explain` command on the CLI app."""
    app.command(
        "explain",
        help=_HELP,
    )(explain)
