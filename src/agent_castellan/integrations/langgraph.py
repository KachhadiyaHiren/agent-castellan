"""LangGraph tool wrapper (WS5)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..guard import Guard
from ..models import Principal


def guard_tools(
    tools: Sequence[Any], guard: Guard, principal_getter: Callable[[], Principal]
) -> list[Any]:
    """Return tools wrapped so each call is authorized by the guard."""
    raise NotImplementedError
