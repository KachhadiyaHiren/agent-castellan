"""Helpers shared by the CLI commands: exit codes, input parsing and policy loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from ..errors import CastellanError
from ..models import Decision, Effect, Principal, ToolCall
from ..policy import engine, loader
from ..policy.schema import Policy

EXIT_ALLOW = 0
EXIT_DENY = 1
EXIT_ASK = 2
EXIT_ERROR = 3

_EFFECT_EXIT = {Effect.ALLOW: EXIT_ALLOW, Effect.DENY: EXIT_DENY, Effect.ASK: EXIT_ASK}

PolicyArg = Annotated[Path, typer.Argument(help="Policy YAML file.")]
RoleOpt = Annotated[str, typer.Option("--role", help="Role of the calling agent.")]
ToolOpt = Annotated[str, typer.Option("--tool", help="Tool name, for example fs.write.")]
ArgsOpt = Annotated[str, typer.Option("--args", help="Tool arguments as a JSON object.")]
DepthOpt = Annotated[int, typer.Option("--depth", min=0, help="Delegation depth of the agent.")]
ParentRoleOpt = Annotated[str | None, typer.Option("--parent-role", help="Role of the parent.")]
BehalfOpt = Annotated[str | None, typer.Option("--on-behalf-of", help="End-user id.")]


def fail(message: str) -> NoReturn:
    """Print an error to stderr and exit with the error code."""
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_ERROR)


def exit_code_for(effect: Effect) -> int:
    """Map a decision effect to the process exit code (allow 0, deny 1, ask 2)."""
    return _EFFECT_EXIT[effect]


def load_policy_or_exit(path: Path) -> Policy:
    """Load a policy, turning any failure into a clean error exit."""
    try:
        return loader.load_policy(path)
    except NotImplementedError:
        fail("the policy loader is not implemented yet")
    except (CastellanError, OSError) as exc:
        fail(str(exc))


def parse_args(text: str) -> dict[str, Any]:
    """Parse the `--args` option; it must be a JSON object."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"--args is not valid JSON: {exc}")
    if not isinstance(value, dict):
        fail("--args must be a JSON object")
    return value


def build_principal(
    role: str, depth: int, parent_role: str | None = None, on_behalf_of: str | None = None
) -> Principal:
    """Build the throwaway principal used for dry-run decisions."""
    return Principal(
        agent_id="cli-agent",
        role=role,
        run_id="cli-run",
        parent_role=parent_role,
        depth=depth,
        on_behalf_of=on_behalf_of,
    )


def decide(policy: Policy, principal: Principal, call: ToolCall) -> Decision:
    """Ask the policy engine for a decision, turning failures into a clean error exit."""
    try:
        return engine.PolicyEngine(policy).decide(principal, call)
    except NotImplementedError:
        fail("the policy engine is not implemented yet")
    except CastellanError as exc:
        fail(str(exc))


def decision_line(decision: Decision) -> str:
    """One-line human summary of a decision."""
    rule = decision.rule_id or "-"
    return (
        f"{decision.effect.value.upper()} rule={rule} source={decision.source} "
        f"reason={decision.reason}"
    )
