from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_castellan.errors import ApprovalRequired, CastellanError, PermissionDenied
from agent_castellan.integrations.decorator import guard_context, guarded
from agent_castellan.models import Effect

from .conftest import Rig


def test_allowed_call_runs_and_is_audited(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    def read(path: str, limit: int = 10) -> str:
        return f"{path}:{limit}"

    with guard_context(rig.principal):
        assert read("/w/a") == "/w/a:10"
    entry = rig.audit.entries[0]
    assert entry.call.tool == "fs.read"
    assert entry.call.args == {"path": "/w/a", "limit": 10}


def test_denied_call_raises_and_body_does_not_run(rig: Rig) -> None:
    ran: list[int] = []

    @guarded(rig.guard, tool="fs.delete")
    def delete(path: str) -> None:
        ran.append(1)

    with guard_context(rig.principal), pytest.raises(PermissionDenied) as info:
        delete("/x")
    assert info.value.decision.effect is Effect.DENY
    assert ran == []


def test_ask_raises_approval_required_then_retry_after_approval(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.write")
    def write(path: str, content: str) -> str:
        return "ok"

    with guard_context(rig.principal):
        with pytest.raises(ApprovalRequired) as info:
            write("/w/a", "x")
        approval_id = info.value.approval_id
        rig.guard.approve(approval_id, approver_id="reviewer-1")
        assert write("/w/a", "x") == "ok"


def test_missing_context_fails_closed(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    def read(path: str) -> str:
        return path

    with pytest.raises(CastellanError, match="no guard context"):
        read("/a")


def test_context_is_restored_after_exit(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    def read(path: str) -> str:
        return path

    with guard_context(rig.principal):
        pass
    with pytest.raises(CastellanError):
        read("/a")


def test_nested_contexts_use_innermost_principal(rig: Rig) -> None:
    other = rig.guard.start_run("researcher")

    @guarded(rig.guard, tool="fs.read")
    def read(path: str) -> str:
        return path

    with guard_context(rig.principal):
        with guard_context(other):
            read("/a")
        read("/b")
    assert [e.principal.role for e in rig.audit.entries] == ["researcher", "coder"]


def test_varargs_and_kwargs_become_args(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    def read(*paths: str, **opts: Any) -> int:
        return len(paths)

    with guard_context(rig.principal):
        assert read("a", "b", mode="r") == 2
    assert rig.audit.entries[0].call.args == {"paths": ["a", "b"], "mode": "r"}


def test_async_function_is_guarded(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    async def read(path: str) -> str:
        return path

    @guarded(rig.guard, tool="fs.delete")
    async def delete(path: str) -> str:
        return path

    async def run() -> str:
        with guard_context(rig.principal):
            with pytest.raises(PermissionDenied):
                await delete("/x")
            return await read("/a")

    assert asyncio.run(run()) == "/a"


def test_wrapper_preserves_metadata(rig: Rig) -> None:
    @guarded(rig.guard, tool="fs.read")
    def read(path: str) -> str:
        """Read a file."""
        return path

    assert read.__name__ == "read"
    assert read.__doc__ == "Read a file."


def test_ask_without_approval_id_is_treated_as_denied(rig: Rig) -> None:
    from agent_castellan.integrations.decorator import enforce
    from agent_castellan.models import Decision, ToolCall

    class OddGuard:
        def authorize(self, *a: Any, **k: Any) -> Decision:
            return Decision(effect=Effect.ASK, reason="odd")

    with pytest.raises(PermissionDenied):
        enforce(OddGuard(), rig.principal, ToolCall(tool="t"), ())  # type: ignore[arg-type]
