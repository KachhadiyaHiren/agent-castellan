"""`castellan approve` command group: list, accept and reject approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..errors import CastellanError
from ..guard import SystemClock
from ..interfaces import ApprovalStore
from ..models import ApprovalStatus
from ..runtime import approvals
from ._common import fail

approve_app = typer.Typer(help="List, accept and reject approvals.", no_args_is_help=True)

StateOpt = Annotated[Path, typer.Option("--state", help="SQLite state file.")]
IdArg = Annotated[str, typer.Argument(help="Approval id.")]
ApproverOpt = Annotated[str, typer.Option("--approver", help="Id of the approving party.")]


def _open_store(state: Path) -> ApprovalStore:
    try:
        return approvals.SqliteApprovalStore(state, SystemClock())
    except NotImplementedError:
        fail("the approval store is not implemented yet")
    except (CastellanError, OSError) as exc:
        fail(str(exc))


@approve_app.command("list")
def list_pending(state: StateOpt) -> None:
    """List approvals that are waiting for a decision."""
    store = _open_store(state)
    try:
        pending = store.pending()
    except NotImplementedError:
        fail("the approval store is not implemented yet")
    if not pending:
        typer.echo("no pending approvals")
        return
    table = Table(title="Pending approvals")
    for column in ("Approval", "Run", "Agent", "Tool", "Args", "Approver", "Rule", "Expires"):
        table.add_column(column)
    for r in pending:
        table.add_row(
            r.approval_id,
            r.principal.run_id,
            f"{r.principal.agent_id} ({r.principal.role})",
            r.call.tool,
            json.dumps(r.call.args, sort_keys=True),
            r.approver,
            r.rule_id,
            r.expires_at.isoformat(),
        )
    Console(highlight=False, width=max(Console().width, 160)).print(table)


def _resolve(approval_id: str, state: Path, approver: str, *, accept: bool) -> None:
    store = _open_store(state)
    try:
        status = store.resolve(approval_id, approver, accept)
    except NotImplementedError:
        fail("the approval store is not implemented yet")
    except (KeyError, CastellanError) as exc:
        fail(f"cannot resolve approval '{approval_id}': {exc}")
    wanted = ApprovalStatus.APPROVED if accept else ApprovalStatus.DENIED
    typer.echo(f"{approval_id}: {status.value}")
    if status is not wanted:
        raise typer.Exit(1)


@approve_app.command("accept")
def accept(approval_id: IdArg, state: StateOpt, approver: ApproverOpt = "human") -> None:
    """Approve a pending request. Exit 1 if it could not be approved."""
    _resolve(approval_id, state, approver, accept=True)


@approve_app.command("reject")
def reject(approval_id: IdArg, state: StateOpt, approver: ApproverOpt = "human") -> None:
    """Reject a pending request. Exit 1 if it could not be rejected."""
    _resolve(approval_id, state, approver, accept=False)


def register(app: typer.Typer) -> None:
    """Register the `approve` command group on the CLI app."""
    app.add_typer(approve_app, name="approve", help="List, accept and reject approvals.")
