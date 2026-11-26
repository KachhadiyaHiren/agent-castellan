"""`castellan check` command: dry-run one call against a policy."""

from __future__ import annotations

import typer

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


def check(
    policy: PolicyArg,
    role: RoleOpt,
    tool: ToolOpt,
    args: ArgsOpt = "{}",
    depth: DepthOpt = 0,
    parent_role: ParentRoleOpt = None,
    on_behalf_of: BehalfOpt = None,
) -> None:
    """Print the decision for one call. Exit 0 allow, 1 deny, 2 ask, 3 error."""
    loaded = load_policy_or_exit(policy)
    call = ToolCall(tool=tool, args=parse_args(args))
    decision = decide(loaded, build_principal(role, depth, parent_role, on_behalf_of), call)
    typer.echo(decision_line(decision))
    raise typer.Exit(exit_code_for(decision.effect))


def register(app: typer.Typer) -> None:
    """Register the `check` command on the CLI app."""
    app.command(
        "check",
        help='Dry-run one tool call against a policy and print the decision.\n\nExit codes: 0 allow, 1 deny, 2 ask (approval needed), 3 error.\n\nExample: castellan check team.yaml --role coder --tool fs.write --args \'{"path": "/workspace/a.py"}\'',
    )(check)
