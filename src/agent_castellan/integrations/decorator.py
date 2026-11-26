"""`@guarded` decorator and guard context for plain Python tools (WS5)."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from typing import Any, TypeVar

from ..guard import Guard
from ..models import Grant, Principal

F = TypeVar("F", bound=Callable[..., Any])


def guard_context(
    principal: Principal, chain: Sequence[Grant] = ()
) -> AbstractContextManager[Iterator[None]]:
    """Set the acting principal and grant chain for guarded calls in this context."""
    raise NotImplementedError


def guarded(guard: Guard, *, tool: str) -> Callable[[F], F]:
    """Wrap a function so every call is authorized before it runs."""
    raise NotImplementedError
