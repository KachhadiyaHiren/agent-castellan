from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("langchain_core")

from langchain_core.tools import BaseTool, tool

from agent_castellan.errors import ApprovalRequired, PermissionDenied
from agent_castellan.integrations.langgraph import guard_tools
from agent_castellan.models import Effect

from .conftest import Rig, make_rig


@tool
def fs_read(path: str) -> str:
    """Read a file."""
    return f"content of {path}"


@tool
def fs_write(path: str, content: str) -> str:
    """Write a file."""
    return "written"


@tool
def fs_delete(path: str) -> str:
    """Delete a file."""
    return "deleted"


def build(rig: Rig, **kw: Any) -> dict[str, BaseTool]:
    tools = guard_tools(
        [_renamed(fs_read, "fs.read"), _renamed(fs_write, "fs.write"), fs_delete],
        rig.guard,
        lambda: rig.principal,
        **kw,
    )
    return {t.name: t for t in tools}


def _renamed(base: BaseTool, name: str) -> BaseTool:
    return base.model_copy(update={"name": name})


@pytest.fixture
def lg_rig() -> Rig:
    return make_rig({"fs.read": Effect.ALLOW, "fs.write": Effect.ASK})


def test_allowed_tool_runs_and_keeps_metadata(lg_rig: Rig) -> None:
    tools = build(lg_rig)
    read = tools["fs.read"]
    assert read.description == "Read a file."
    assert read.invoke({"path": "/a"}) == "content of /a"
    assert lg_rig.audit.entries[0].call.tool == "fs.read"
    assert lg_rig.audit.entries[0].call.args == {"path": "/a"}


def test_denied_tool_raises_by_default(lg_rig: Rig) -> None:
    with pytest.raises(PermissionDenied):
        build(lg_rig)["fs_delete"].invoke({"path": "/a"})


def test_ask_raises_approval_required_and_succeeds_after_approval(lg_rig: Rig) -> None:
    write = build(lg_rig)["fs.write"]
    args = {"path": "/a", "content": "x"}
    with pytest.raises(ApprovalRequired) as info:
        write.invoke(args)
    lg_rig.guard.approve(info.value.approval_id, approver_id="reviewer")
    assert write.invoke(args) == "written"


def test_message_mode_returns_refusal_text(lg_rig: Rig) -> None:
    tools = build(lg_rig, on_denied="message")
    assert tools["fs_delete"].invoke({"path": "/a"}).startswith("denied:")
    assert (
        tools["fs.write"]
        .invoke({"path": "/a", "content": "x"})
        .startswith("approval required: appr-")
    )


def test_message_mode_denies_ask_without_id(lg_rig: Rig) -> None:
    class OddGuard:
        def authorize(self, *a: Any, **k: Any) -> Any:
            from agent_castellan.models import Decision

            return Decision(effect=Effect.ASK, reason="odd")

    tools = guard_tools(
        [fs_read],
        OddGuard(),
        lambda: lg_rig.principal,
        on_denied="message",  # type: ignore[arg-type]
    )
    assert tools[0].invoke({"path": "/a"}) == "denied: odd"


def test_async_invocation_is_guarded(lg_rig: Rig) -> None:
    tools = build(lg_rig)

    async def run() -> str:
        with pytest.raises(PermissionDenied):
            await tools["fs_delete"].ainvoke({"path": "/a"})
        return str(await tools["fs.read"].ainvoke({"path": "/b"}))

    assert asyncio.run(run()) == "content of /b"


def test_principal_getter_is_read_on_every_call(lg_rig: Rig) -> None:
    other = lg_rig.guard.start_run("researcher")
    current = [lg_rig.principal]
    tools = guard_tools([_renamed(fs_read, "fs.read")], lg_rig.guard, lambda: current[0])
    tools[0].invoke({"path": "/a"})
    current[0] = other
    tools[0].invoke({"path": "/a"})
    assert [e.principal.role for e in lg_rig.audit.entries] == ["coder", "researcher"]


def test_chain_getter_is_passed_to_guard(lg_rig: Rig) -> None:
    seen: list[Any] = []
    lg_rig.decider.delegations = {"coder": ("researcher",)}
    child, grant = lg_rig.guard.delegate(lg_rig.principal, "researcher", tools=["fs.read"])
    tools = guard_tools(
        [_renamed(fs_read, "fs.read")],
        lg_rig.guard,
        lambda: child,
        chain_getter=lambda: seen.append(1) or [grant],
    )
    assert tools[0].invoke({"path": "/a"}) == "content of /a"
    assert seen == [1]


def test_plain_callable_is_wrapped_and_guarded(lg_rig: Rig) -> None:
    def fs_read_plain(path: str, limit: int = 5) -> str:
        """Read plain."""
        return f"{path}:{limit}"

    def fs_other(path: str) -> str:
        """Other."""
        return path

    allow = make_rig({"fs_read_plain": Effect.ALLOW})
    tools = guard_tools([fs_read_plain, fs_other], allow.guard, lambda: allow.principal)
    assert tools[0].invoke({"path": "/a"}) == "/a:5"
    assert allow.audit.entries[0].call.args == {"path": "/a", "limit": 5}
    with pytest.raises(PermissionDenied):
        tools[1].invoke({"path": "/a"})


def test_non_tool_input_is_rejected(lg_rig: Rig) -> None:
    with pytest.raises(TypeError, match="cannot guard"):
        guard_tools([42], lg_rig.guard, lambda: lg_rig.principal)
