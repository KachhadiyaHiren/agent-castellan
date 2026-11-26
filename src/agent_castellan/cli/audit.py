"""`castellan audit` command group: verify and tail audit logs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from ..audit import verify as audit_verify
from ..errors import CastellanError
from ..models import AuditEntry
from ._common import fail

audit_app = typer.Typer(help="Verify and tail audit logs.", no_args_is_help=True)

FileArg = Annotated[Path, typer.Argument(help="Audit log (JSONL) file.")]


@audit_app.command("verify")
def verify(file: FileArg) -> None:
    """Verify the hash chain. Exit 0 if intact, 1 if tampered, 3 on failure to read."""
    try:
        result = audit_verify.verify_log(file)
    except NotImplementedError:
        fail("the audit verifier is not implemented yet")
    except (CastellanError, OSError) as exc:
        fail(str(exc))
    if result.ok:
        typer.echo(f"OK: {result.entries} entries verified")
        return
    typer.echo(f"FAILED at seq {result.bad_seq}: {result.reason}")
    raise typer.Exit(1)


def _read_entries(file: Path) -> list[AuditEntry]:
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(str(exc))
    entries: list[AuditEntry] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(AuditEntry.model_validate_json(line))
        except ValidationError:
            fail(f"{file}:{number}: not a valid audit entry")
    return entries


@audit_app.command("tail")
def tail(
    file: FileArg,
    run: Annotated[str | None, typer.Option("--run", help="Only entries of this run id.")] = None,
    lines: Annotated[int, typer.Option("-n", "--lines", min=1, help="Entries to show.")] = 20,
) -> None:
    """Show the most recent audit entries, optionally for one run."""
    entries = _read_entries(file)
    if run is not None:
        entries = [e for e in entries if e.principal.run_id == run]
    for e in entries[-lines:]:
        rule = e.decision.rule_id or "-"
        typer.echo(
            f"{e.seq} {e.at.isoformat()} run={e.principal.run_id} agent={e.principal.agent_id} "
            f"role={e.principal.role} tool={e.call.tool} effect={e.decision.effect.value} "
            f"rule={rule}"
        )


def register(app: typer.Typer) -> None:
    """Register the `audit` command group on the CLI app."""
    app.add_typer(audit_app, name="audit", help="Verify and tail audit logs.")
