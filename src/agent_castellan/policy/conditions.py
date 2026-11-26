"""Condition DSL compiler and evaluator (PLAN.md §3.2).

The `when` block is data only: it is compiled once into closures and nothing is ever
passed to `eval`. `compile_condition` and `build_context` keep their Phase 0 signatures.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from ..errors import PolicyError
from ..models import Principal, ToolCall
from .normalize import lexical_path, tool_namespace

Context = Mapping[str, Any]
Condition = Callable[[Context], bool]
Predicate = Callable[[Any], bool]

MAX_REGEX_LENGTH = 512

_MISSING = object()

# Paths whose roots have a fixed set of keys; `args` is free-form.
_FIXED_PATHS: dict[str, frozenset[str]] = {
    "agent": frozenset({"id", "role", "depth", "parent_role", "on_behalf_of"}),
    "tool": frozenset({"name", "namespace"}),
    "run": frozenset({"id", "tool_calls"}),
    "time": frozenset({"hour_utc", "weekday"}),
}


def build_context(
    principal: Principal,
    call: ToolCall,
    *,
    run_tool_calls: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the evaluation context (`agent`, `tool`, `args`, `run`, `time`) for a call."""
    agent: dict[str, Any] = {
        "id": principal.agent_id,
        "role": principal.role,
        "depth": principal.depth,
    }
    if principal.parent_role is not None:
        agent["parent_role"] = principal.parent_role
    if principal.on_behalf_of is not None:
        agent["on_behalf_of"] = principal.on_behalf_of
    context: dict[str, Any] = {
        "agent": agent,
        "tool": {"name": call.tool, "namespace": tool_namespace(call.tool)},
        "args": call.args,
        "run": {"id": principal.run_id, "tool_calls": run_tool_calls},
    }
    if now is not None:
        context["time"] = {"hour_utc": now.hour, "weekday": now.weekday()}
    return context


def _lookup(context: Context, parts: tuple[str, ...]) -> Any:
    current: Any = context
    for part in parts:
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
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


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _same(a: Any, b: Any) -> bool:
    """Equality that never treats a bool as a number."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return bool(a == b)


@dataclass(frozen=True)
class OperatorSpec:
    """One entry of the operator registry (also used to generate the reference docs)."""

    name: str
    operand: str
    description: str
    build: Callable[[Any], Predicate]
    check: Callable[[Any], bool]


def _op_eq(operand: Any) -> Predicate:
    return lambda value: _same(value, operand)


def _op_ne(operand: Any) -> Predicate:
    return lambda value: not _same(value, operand)


def _member(operand: list[Any] | tuple[Any, ...]) -> Predicate:
    if all(isinstance(item, str) for item in operand):
        strings = frozenset(operand)
        return lambda value: isinstance(value, str) and value in strings
    return lambda value: any(_same(value, item) for item in operand)


def _op_in(operand: Any) -> Predicate:
    return _member(operand)


def _op_not_in(operand: Any) -> Predicate:
    member = _member(operand)
    return lambda value: not member(value)


def _numeric(compare: Callable[[Any, Any], bool]) -> Callable[[Any], Predicate]:
    def build(operand: Any) -> Predicate:
        return lambda value: _is_number(value) and compare(value, operand)

    return build


def _op_glob(operand: Any) -> Predicate:
    regex = _glob_regex(operand)

    def glob(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        if "/" in value:
            value = lexical_path(value)
        return regex.fullmatch(value) is not None

    return glob


def _op_regex(operand: Any) -> Predicate:
    try:
        regex = re.compile(operand)
    except re.error as exc:
        raise PolicyError(f"invalid regular expression {operand!r}: {exc}") from exc
    return lambda value: isinstance(value, str) and regex.fullmatch(value) is not None


def _op_contains(operand: Any) -> Predicate:
    def contains(value: Any) -> bool:
        if isinstance(value, str):
            return isinstance(operand, str) and operand in value
        if isinstance(value, list | tuple):
            return any(_same(item, operand) for item in value)
        return False

    return contains


def _op_starts_with(operand: Any) -> Predicate:
    return lambda value: isinstance(value, str) and value.startswith(operand)


def _op_ends_with(operand: Any) -> Predicate:
    return lambda value: isinstance(value, str) and value.endswith(operand)


def _op_exists(operand: Any) -> Predicate:
    return lambda _value: bool(operand)  # only reached when the path is present


def _length(compare: Callable[[int, int], bool]) -> Callable[[Any], Predicate]:
    def build(operand: Any) -> Predicate:
        return lambda value: isinstance(value, str | list | tuple) and compare(len(value), operand)

    return build


def _valid_regex(operand: Any) -> bool:
    return isinstance(operand, str) and len(operand) <= MAX_REGEX_LENGTH


def _is_int(operand: Any) -> bool:
    return isinstance(operand, int) and not isinstance(operand, bool) and operand >= 0


def _list_of_scalars(operand: Any) -> bool:
    return isinstance(operand, list | tuple) and all(_is_scalar(item) for item in operand)


OPERATORS: dict[str, OperatorSpec] = {
    spec.name: spec
    for spec in (
        OperatorSpec("eq", "scalar", "equality", _op_eq, _is_scalar),
        OperatorSpec("ne", "scalar", "inequality", _op_ne, _is_scalar),
        OperatorSpec("in", "list", "membership", _op_in, _list_of_scalars),
        OperatorSpec("not_in", "list", "non-membership", _op_not_in, _list_of_scalars),
        OperatorSpec("lt", "number", "less than", _numeric(lambda a, b: a < b), _is_number),
        OperatorSpec("lte", "number", "less or equal", _numeric(lambda a, b: a <= b), _is_number),
        OperatorSpec("gt", "number", "greater than", _numeric(lambda a, b: a > b), _is_number),
        OperatorSpec(
            "gte", "number", "greater or equal", _numeric(lambda a, b: a >= b), _is_number
        ),
        OperatorSpec(
            "glob",
            "string",
            "path-style glob (`**` crosses `/`), applied after path normalization",
            _op_glob,
            lambda operand: isinstance(operand, str),
        ),
        OperatorSpec(
            "regex",
            "string",
            f"`re.fullmatch`, compiled at load time, pattern at most {MAX_REGEX_LENGTH} chars",
            _op_regex,
            _valid_regex,
        ),
        OperatorSpec(
            "contains",
            "scalar",
            "substring (str) or element (list)",
            _op_contains,
            _is_scalar,
        ),
        OperatorSpec(
            "starts_with",
            "string",
            "string prefix",
            _op_starts_with,
            lambda operand: isinstance(operand, str),
        ),
        OperatorSpec(
            "ends_with",
            "string",
            "string suffix",
            _op_ends_with,
            lambda operand: isinstance(operand, str),
        ),
        OperatorSpec(
            "exists", "bool", "path present or absent", _op_exists, lambda o: isinstance(o, bool)
        ),
        OperatorSpec(
            "len_lte",
            "int",
            "length of a string or list is at most",
            _length(lambda a, b: a <= b),
            _is_int,
        ),
        OperatorSpec(
            "len_gte",
            "int",
            "length of a string or list is at least",
            _length(lambda a, b: a >= b),
            _is_int,
        ),
    )
}


def _split_path(path: Any) -> tuple[str, ...]:
    if not isinstance(path, str) or not path:
        raise PolicyError(f"condition path must be a non-empty string, got {path!r}")
    parts = tuple(path.split("."))
    if any(not part for part in parts):
        raise PolicyError(f"invalid condition path '{path}'")
    root = parts[0]
    if root != "args" and root not in _FIXED_PATHS:
        known = ", ".join(sorted([*_FIXED_PATHS, "args"]))
        raise PolicyError(f"unknown path '{path}': must start with one of {known}")
    if root in _FIXED_PATHS and (len(parts) != 2 or parts[1] not in _FIXED_PATHS[root]):
        allowed = ", ".join(f"{root}.{key}" for key in sorted(_FIXED_PATHS[root]))
        raise PolicyError(f"unknown path '{path}': expected one of {allowed}")
    return parts


def _compile_leaf(path: Any, spec: Any) -> Condition:
    parts = _split_path(path)
    if not isinstance(spec, Mapping) or not spec:
        raise PolicyError(f"condition for '{path}' must be a mapping of operator to operand")
    predicates: list[Predicate] = []
    absent_ok = True
    for name, operand in spec.items():
        operator = OPERATORS.get(name) if isinstance(name, str) else None
        if operator is None:
            raise PolicyError(f"unknown operator '{name}' for '{path}'")
        if not operator.check(operand):
            raise PolicyError(
                f"operator '{name}' for '{path}' expects a {operator.operand} operand, "
                f"got {operand!r}"
            )
        predicates.append(operator.build(operand))
        absent_ok = absent_ok and name == "exists" and operand is False

    if len(predicates) == 1:
        only = predicates[0]

        def evaluate_one(context: Context) -> bool:
            value = _lookup(context, parts)
            return absent_ok if value is _MISSING else only(value)

        return evaluate_one

    def evaluate(context: Context) -> bool:
        value = _lookup(context, parts)
        if value is _MISSING:
            return absent_ok
        return all(predicate(value) for predicate in predicates)

    return evaluate


def _compile_list(kind: str, items: Any) -> list[Condition]:
    if not isinstance(items, list | tuple) or not items:
        raise PolicyError(f"'{kind}' must be a non-empty list of conditions")
    subs: list[Condition] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise PolicyError(f"every entry of '{kind}' must be a mapping")
        subs.append(compile_condition(item))
    return subs


def compile_condition(spec: Mapping[str, Any]) -> Condition:
    """Compile a `when` block into a closure that evaluates it against a context."""
    if not isinstance(spec, Mapping):
        raise PolicyError("a condition must be a mapping")
    parts: list[Condition] = []
    for key, value in spec.items():
        if key == "all":
            all_subs = _compile_list("all", value)
            parts.append(lambda ctx, subs=all_subs: all(sub(ctx) for sub in subs))  # type: ignore[misc]
        elif key == "any":
            any_subs = _compile_list("any", value)
            parts.append(lambda ctx, subs=any_subs: any(sub(ctx) for sub in subs))  # type: ignore[misc]
        elif key == "not":
            if not isinstance(value, Mapping):
                raise PolicyError("'not' must be a mapping")
            inner = compile_condition(value)
            parts.append(lambda ctx, inner=inner: not inner(ctx))  # type: ignore[misc]
        else:
            parts.append(_compile_leaf(key, value))
    if len(parts) == 1:
        return parts[0]
    return lambda ctx: all(part(ctx) for part in parts)


def referenced_paths(spec: Mapping[str, Any]) -> frozenset[str]:
    """Return every dotted path a `when` block reads (used to skip unneeded context work)."""
    found: set[str] = set()
    for key, value in spec.items():
        if key in ("all", "any"):
            for item in value:
                found |= referenced_paths(item)
        elif key == "not":
            found |= referenced_paths(value)
        else:
            found.add(key)
    return frozenset(found)
