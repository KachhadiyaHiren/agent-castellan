"""`castellan lint` command: static checks on a policy."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

import typer

from ..analysis import lint as analysis
from ..errors import CastellanError
from ._common import PolicyArg, fail, load_policy_or_exit


class OutputFormat(StrEnum):
    """Supported `--format` values."""

    TEXT = "text"
    JSON = "json"
    GITHUB = "github"


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _render(findings: list[analysis.Finding], fmt: OutputFormat, file: str) -> list[str]:
    if fmt is OutputFormat.JSON:
        return [json.dumps([vars(f) for f in findings], indent=2)]
    lines: list[str] = []
    for f in findings:
        if fmt is OutputFormat.GITHUB:
            level = "error" if f.severity == "error" else "warning"
            line = f",line={f.line}" if f.line is not None else ""
            lines.append(f"::{level} file={file}{line},title={f.check_id}::{_escape(f.message)}")
        else:
            where = f"{file}:{f.line}" if f.line is not None else file
            rule = f" [{f.rule_id}]" if f.rule_id else ""
            lines.append(f"{where}: {f.severity} {f.check_id} {f.message}{rule}")
    if fmt is OutputFormat.TEXT and not findings:
        lines.append("no issues found")
    return lines


def lint(
    policy: PolicyArg,
    format: Annotated[OutputFormat, typer.Option("--format", help="Output format.")] = (
        OutputFormat.TEXT
    ),
) -> None:
    """Lint a policy. Exit 1 when any error-severity finding exists, 3 on failure to load."""
    loaded = load_policy_or_exit(policy)
    try:
        findings = analysis.lint_policy(loaded)
    except NotImplementedError:
        fail("the policy linter is not implemented yet")
    except CastellanError as exc:
        fail(str(exc))
    for line in _render(findings, format, str(policy)):
        typer.echo(line)
    raise typer.Exit(1 if any(f.severity == "error" for f in findings) else 0)


def register(app: typer.Typer) -> None:
    """Register the `lint` command on the CLI app."""
    app.command("lint", help="Lint a policy.")(lint)
