"""LangGraph tool wrapper (WS5).

Example::

    from langgraph.prebuilt import ToolNode
    from agent_castellan import Guard
    from agent_castellan.integrations.decorator import guard_context
    from agent_castellan.integrations.langgraph import guard_tools

    guard = Guard.from_file("team.yaml")
    me = guard.start_run("researcher")

    safe_tools = guard_tools([web_search, fs_read], guard, lambda: me)
    node = ToolNode(safe_tools, handle_tool_errors=True)  # denials become tool messages
    # ... build and run the graph as usual; tool names are the policy tool names.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Sequence
from typing import Any, Literal

from ..guard import Guard
from ..models import Effect, Grant, Principal, ToolCall
from .decorator import enforce

OnDenied = Literal["raise", "message"]


def guard_tools(
    tools: Sequence[Any],
    guard: Guard,
    principal_getter: Callable[[], Principal],
    *,
    chain_getter: Callable[[], Sequence[Grant]] | None = None,
    on_denied: OnDenied = "raise",
) -> list[Any]:
    """Return tools wrapped so each call is authorized by the guard.

    With `on_denied="raise"` (default) a refusal raises `PermissionDenied` or
    `ApprovalRequired`; with `"message"` the tool returns the refusal as text instead so the
    model can adapt. Requires `langchain-core` (installed with the `[langgraph]` extra).
    """
    from langchain_core.tools import BaseTool, StructuredTool

    def authorize(name: str, args: dict[str, Any]) -> str | None:
        chain = chain_getter() if chain_getter is not None else ()
        principal = principal_getter()
        call = ToolCall(tool=name, args=args)
        if on_denied == "raise":
            enforce(guard, principal, call, chain)
            return None
        decision = guard.authorize(principal, call, chain=chain)
        if decision.effect is Effect.ALLOW:
            return None
        if decision.effect is Effect.ASK and decision.approval_id:
            return f"approval required: {decision.approval_id}"
        return f"denied: {decision.reason}"

    wrapped: list[Any] = []
    for tool in tools:
        if isinstance(tool, BaseTool):
            wrapped.append(_wrap_base_tool(tool, authorize, StructuredTool))
        elif callable(tool):
            wrapped.append(_wrap_callable(tool, authorize, StructuredTool))
        else:
            raise TypeError(f"cannot guard {type(tool).__name__}: expected a tool or a callable")
    return wrapped


def _wrap_base_tool(tool: Any, authorize: Callable[..., str | None], structured: Any) -> Any:
    def run(**kwargs: Any) -> Any:
        refusal = authorize(tool.name, kwargs)
        return refusal if refusal is not None else tool.invoke(kwargs)

    async def arun(**kwargs: Any) -> Any:
        refusal = authorize(tool.name, kwargs)
        return refusal if refusal is not None else await tool.ainvoke(kwargs)

    return structured(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        func=run,
        coroutine=arun,
        return_direct=tool.return_direct,
    )


def _wrap_callable(func: Callable[..., Any], authorize: Callable[..., str | None], st: Any) -> Any:
    name = func.__name__
    signature = inspect.signature(func)

    @functools.wraps(func)
    def run(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        refusal = authorize(name, dict(bound.arguments))
        return refusal if refusal is not None else func(*args, **kwargs)

    return st.from_function(
        func=run, name=name, description=func.__doc__ or name, infer_schema=True
    )
