"""Condition DSL compiler and evaluator.

Phase 0 ships only `eq`, `in` and `glob` (plus the `all`/`any`/`not` combinators) so that
delegation can be built against the final signatures. WS1 replaces the bodies, keeping
`compile_condition` and `build_context` signatures unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import lru_cache
from typing import Any

from ..errors import PolicyError
from ..models import Principal, ToolCall

Context = Mapping[str, Any]
Condition = Callable[[Context], bool]

_MISSING = object()


def build_context(
    principal: Principal,
    call: ToolCall,
    *,
    run_tool_calls: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the evaluation context (`agent`, `tool`, `args`, `run`, `time`) for a call."""
    namespace = re.split(r"[.:]", call.tool, maxsplit=1)[0]
    context: dict[str, Any] = {
        "agent": {
            "id": principal.agent_id,
            "role": principal.role,
            "depth": principal.depth,
            "parent_role": principal.parent_role,
            "on_behalf_of": principal.on_behalf_of,
        },
        "tool": {"name": call.tool, "namespace": namespace},
        "args": call.args,
        "run": {"id": principal.run_id, "tool_calls": run_tool_calls},
    }
    if now is not None:
        context["time"] = {"hour_utc": now.hour, "weekday": now.weekday()}
    return context


def _lookup(context: Context, path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list | tuple) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                if pattern[i : i + 1] == "/":
                    # "**/" also matches zero directories
                    out[-1] = "(?:.*/)?"
                    i += 1
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def _op_eq(value: Any, operand: Any) -> bool:
    return bool(value == operand)


def _op_in(value: Any, operand: Any) -> bool:
    return value in operand


def _op_glob(value: Any, operand: Any) -> bool:
    return isinstance(value, str) and _glob_regex(operand).fullmatch(value) is not None


_OPERATORS: dict[str, tuple[Callable[[Any, Any], bool], type | tuple[type, ...]]] = {
    "eq": (_op_eq, object),
    "in": (_op_in, (list, tuple)),
    "glob": (_op_glob, str),
}


def _compile_leaf(path: str, spec: Any) -> Condition:
    if not isinstance(spec, Mapping) or not spec:
        raise PolicyError(f"condition for '{path}' must be a mapping of operator to operand")
    checks: list[tuple[Callable[[Any, Any], bool], Any]] = []
    for name, operand in spec.items():
        if name not in _OPERATORS:
            raise PolicyError(f"unknown operator '{name}' for '{path}'")
        func, operand_type = _OPERATORS[name]
        if not isinstance(operand, operand_type):
            raise PolicyError(f"operator '{name}' for '{path}' has the wrong operand type")
        checks.append((func, operand))

    def evaluate(context: Context) -> bool:
        value = _lookup(context, path)
        if value is _MISSING:
            return False
        return all(func(value, operand) for func, operand in checks)

    return evaluate


def compile_condition(spec: Mapping[str, Any]) -> Condition:
    """Compile a `when` block into a closure that evaluates it against a context."""
    parts: list[Condition] = []
    for key, value in spec.items():
        if key in ("all", "any"):
            if not isinstance(value, list | tuple):
                raise PolicyError(f"'{key}' must be a list of conditions")
            subs = [compile_condition(item) for item in value]
            parts.append(_combine(key, subs))
        elif key == "not":
            if not isinstance(value, Mapping):
                raise PolicyError("'not' must be a mapping")
            inner = compile_condition(value)
            parts.append(lambda ctx, inner=inner: not inner(ctx))  # type: ignore[misc]
        else:
            parts.append(_compile_leaf(key, value))
    return lambda ctx: all(part(ctx) for part in parts)


def _combine(kind: str, subs: list[Condition]) -> Condition:
    if kind == "all":
        return lambda ctx: all(sub(ctx) for sub in subs)
    return lambda ctx: any(sub(ctx) for sub in subs)
