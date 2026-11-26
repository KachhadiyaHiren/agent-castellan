"""`@guarded` decorator and guard context for plain Python tools (WS5)."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar, cast

from ..errors import ApprovalRequired, CastellanError, PermissionDenied
from ..guard import Guard
from ..models import Decision, Effect, Grant, Principal, ToolCall

F = TypeVar("F", bound=Callable[..., Any])

_CONTEXT: ContextVar[tuple[Principal, tuple[Grant, ...]] | None] = ContextVar(
    "castellan_guard_context", default=None
)


@contextmanager
def guard_context(principal: Principal, chain: Sequence[Grant] = ()) -> Iterator[None]:
    """Set the acting principal and grant chain for guarded calls in this context."""
    token = _CONTEXT.set((principal, tuple(chain)))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_context() -> tuple[Principal, tuple[Grant, ...]]:
    """Return the active principal and chain; fail closed when none is set."""
    active = _CONTEXT.get()
    if active is None:
        raise CastellanError("no guard context: wrap the call in `guard_context(principal, chain)`")
    return active


def enforce(guard: Guard, principal: Principal, call: ToolCall, chain: Sequence[Grant]) -> Decision:
    """Authorize a call and raise unless it is allowed."""
    decision = guard.authorize(principal, call, chain=chain)
    if decision.effect is Effect.ALLOW:
        return decision
    if decision.effect is Effect.ASK:
        if decision.approval_id is None:
            raise PermissionDenied(
                decision.model_copy(
                    update={"effect": Effect.DENY, "reason": "approval needed but no id issued"}
                )
            )
        raise ApprovalRequired(decision.approval_id, decision)
    raise PermissionDenied(decision)


def _json_safe_args(bound: inspect.BoundArguments) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        param = bound.signature.parameters[name]
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            args.update(value)
        elif param.kind is inspect.Parameter.VAR_POSITIONAL:
            args[name] = list(value)
        else:
            args[name] = value
    return args


def guarded(guard: Guard, *, tool: str) -> Callable[[F], F]:
    """Wrap a function so every call is authorized before it runs."""

    def decorate(func: F) -> F:
        signature = inspect.signature(func)

        def authorize(*args: Any, **kwargs: Any) -> None:
            principal, chain = current_context()
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            call = ToolCall(tool=tool, args=_json_safe_args(bound))
            enforce(guard, principal, call, chain)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                authorize(*args, **kwargs)
                return await func(*args, **kwargs)

            return cast(F, awrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            authorize(*args, **kwargs)
            return func(*args, **kwargs)

        return cast(F, wrapper)

    return decorate
