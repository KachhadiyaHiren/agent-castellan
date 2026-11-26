"""`castellan approve list|accept|reject`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.errors import CastellanError
from agent_castellan.models import ApprovalStatus, Principal, ToolCall
from agent_castellan.runtime import approvals as approvals_mod
from agent_castellan.testing.fakes import FakeApprovalStore, FrozenClock

Invoke = Callable[..., Any]


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeApprovalStore:
    fake = FakeApprovalStore(FrozenClock())
    opened: list[Path] = []

    def factory(path: str | Path, clock: object) -> FakeApprovalStore:
        opened.append(Path(path))
        return fake

    monkeypatch.setattr(approvals_mod, "SqliteApprovalStore", factory)
    fake.opened = opened  # type: ignore[attr-defined]
    return fake


def add(store: FakeApprovalStore, tool: str = "fs.write") -> str:
    principal = Principal(agent_id="coder-1", role="coder", run_id="run-1")
    call = ToolCall(tool=tool, args={"path": "/workspace/a.py"})
    return store.create(principal, call, "write-needs-review", "role:reviewer", 600).approval_id


def test_list_empty(invoke: Invoke, store: FakeApprovalStore, tmp_path: Path) -> None:
    result = invoke("approve", "list", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 0
    assert "no pending approvals" in result.output
    assert store.opened == [tmp_path / "s.db"]  # type: ignore[attr-defined]


def test_list_shows_pending(invoke: Invoke, store: FakeApprovalStore, tmp_path: Path) -> None:
    first = add(store)
    add(store, "fs.delete")
    store.resolve("appr-2", "human", True)
    result = invoke("approve", "list", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 0
    assert first in result.output
    assert "fs.write" in result.output
    assert "role:reviewer" in result.output
    assert "fs.delete" not in result.output


def test_accept_approves(invoke: Invoke, store: FakeApprovalStore, tmp_path: Path) -> None:
    approval_id = add(store)
    result = invoke("approve", "accept", approval_id, "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 0
    assert f"{approval_id}: approved" in result.output
    assert store.status[approval_id] is ApprovalStatus.APPROVED


def test_reject_denies(invoke: Invoke, store: FakeApprovalStore, tmp_path: Path) -> None:
    approval_id = add(store)
    result = invoke(
        "approve", "reject", approval_id, "--state", str(tmp_path / "s.db"), "--approver", "bob"
    )
    assert result.exit_code == 0
    assert store.status[approval_id] is ApprovalStatus.DENIED


def test_accept_fails_when_not_pending(
    invoke: Invoke, store: FakeApprovalStore, tmp_path: Path
) -> None:
    approval_id = add(store)
    store.resolve(approval_id, "human", False)
    result = invoke("approve", "accept", approval_id, "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 1
    assert "denied" in result.output


def test_self_approval_refused_exit_one(
    invoke: Invoke, store: FakeApprovalStore, tmp_path: Path
) -> None:
    approval_id = add(store)
    result = invoke(
        "approve", "accept", approval_id, "--state", str(tmp_path / "s.db"), "--approver", "coder-1"
    )
    assert result.exit_code == 1
    assert "pending" in result.output


def test_unknown_id(invoke: Invoke, store: FakeApprovalStore, tmp_path: Path) -> None:
    result = invoke("approve", "accept", "appr-999", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 3
    assert "appr-999" in result.output


@pytest.mark.parametrize("sub", ["list", "accept", "reject"])
def test_store_unimplemented(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sub: str
) -> None:
    def stub(path: str | Path, clock: object) -> None:
        raise NotImplementedError

    monkeypatch.setattr(approvals_mod, "SqliteApprovalStore", stub)
    args = ["approve", sub, *(["x"] if sub != "list" else []), "--state", str(tmp_path / "s.db")]
    result = invoke(*args)
    assert result.exit_code == 3
    assert "not implemented" in result.output


def test_store_open_error(invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(path: str | Path, clock: object) -> None:
        raise CastellanError("corrupt state")

    monkeypatch.setattr(approvals_mod, "SqliteApprovalStore", boom)
    result = invoke("approve", "list", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 3
    assert "corrupt state" in result.output


def test_list_unimplemented_pending(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Stub:
        def __init__(self, path: object, clock: object) -> None: ...

        def pending(self) -> None:
            raise NotImplementedError

    monkeypatch.setattr(approvals_mod, "SqliteApprovalStore", Stub)
    result = invoke("approve", "list", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 3


def test_resolve_unimplemented(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Stub:
        def __init__(self, path: object, clock: object) -> None: ...

        def resolve(self, *args: object) -> None:
            raise NotImplementedError

    monkeypatch.setattr(approvals_mod, "SqliteApprovalStore", Stub)
    result = invoke("approve", "accept", "x", "--state", str(tmp_path / "s.db"))
    assert result.exit_code == 3
