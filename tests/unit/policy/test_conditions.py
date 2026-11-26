"""Condition DSL: every operator, combinators, paths and load-time errors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.models import Principal, ToolCall
from agent_castellan.policy.conditions import (
    OPERATORS,
    build_context,
    compile_condition,
    referenced_paths,
)

AGENT = Principal(
    agent_id="a1", run_id="r1", role="coder", depth=2, parent_role="planner", on_behalf_of="u1"
)
ARGS: dict[str, Any] = {
    "path": "/workspace/src/app.py",
    "amount": 50,
    "ratio": 0.5,
    "flag": True,
    "name": "Hello World",
    "tags": ["a", "b"],
    "empty": "",
    "nothing": None,
    "items": [{"name": "first"}, {"name": "second"}],
    "nested": {"deep": {"x": 1}},
}


def ctx(**kw: Any) -> dict[str, Any]:
    return build_context(AGENT, ToolCall(tool="fs.write", args=ARGS), **kw)


def holds(spec: dict[str, Any], **kw: Any) -> bool:
    return compile_condition(spec)(ctx(**kw))


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        # eq / ne
        ({"args.amount": {"eq": 50}}, True),
        ({"args.amount": {"eq": 50.0}}, True),
        ({"args.amount": {"eq": 51}}, False),
        ({"args.name": {"eq": "Hello World"}}, True),
        ({"args.name": {"eq": "hello world"}}, False),
        ({"args.flag": {"eq": True}}, True),
        ({"args.flag": {"eq": 1}}, False),  # bool is never a number
        ({"args.amount": {"eq": True}}, False),
        ({"args.nothing": {"eq": None}}, True),
        ({"args.amount": {"ne": 51}}, True),
        ({"args.amount": {"ne": 50}}, False),
        ({"args.flag": {"ne": 1}}, True),
        ({"args.missing": {"ne": 1}}, False),  # missing makes every operator false
        # in / not_in
        ({"args.name": {"in": ["Hello World", "x"]}}, True),
        ({"args.name": {"in": ["x", "y"]}}, False),
        ({"args.amount": {"in": [1, 50, "x"]}}, True),
        ({"args.flag": {"in": [1]}}, False),
        ({"args.tags": {"in": ["a"]}}, False),  # list value is never a member
        ({"args.name": {"not_in": ["x"]}}, True),
        ({"args.name": {"not_in": ["Hello World"]}}, False),
        ({"args.amount": {"not_in": [1, 2]}}, True),
        ({"args.missing": {"not_in": ["x"]}}, False),
        # numeric comparisons
        ({"args.amount": {"lt": 51}}, True),
        ({"args.amount": {"lt": 50}}, False),
        ({"args.amount": {"lte": 50}}, True),
        ({"args.amount": {"lte": 49}}, False),
        ({"args.amount": {"gt": 49}}, True),
        ({"args.amount": {"gt": 50}}, False),
        ({"args.amount": {"gte": 50}}, True),
        ({"args.amount": {"gte": 51}}, False),
        ({"args.ratio": {"lt": 1}}, True),
        ({"args.name": {"lt": 5}}, False),  # non-number
        ({"args.flag": {"gte": 0}}, False),  # bool is not a number
        ({"args.nothing": {"lte": 1}}, False),
        ({"args.amount": {"gt": 10, "lt": 100}}, True),
        ({"args.amount": {"gt": 10, "lt": 20}}, False),
        # glob
        ({"args.path": {"glob": "/workspace/**"}}, True),
        ({"args.path": {"glob": "/workspace/*"}}, False),
        ({"args.path": {"glob": "/workspace/src/*.py"}}, True),
        ({"args.path": {"glob": "**/*.py"}}, True),
        ({"args.path": {"glob": "**/.env*"}}, False),
        ({"args.path": {"glob": "/workspace/src/app.p?"}}, True),
        ({"args.path": {"glob": "/other/**"}}, False),
        ({"args.amount": {"glob": "*"}}, False),
        # regex
        ({"args.name": {"regex": r"Hello \w+"}}, True),
        ({"args.name": {"regex": r"Hello"}}, False),  # fullmatch, not search
        ({"args.name": {"regex": r"(?i)hello world"}}, True),
        ({"args.amount": {"regex": r"\d+"}}, False),
        # contains
        ({"args.name": {"contains": "lo Wo"}}, True),
        ({"args.name": {"contains": "xyz"}}, False),
        ({"args.name": {"contains": 5}}, False),
        ({"args.tags": {"contains": "a"}}, True),
        ({"args.tags": {"contains": "z"}}, False),
        ({"args.amount": {"contains": 5}}, False),
        # starts_with / ends_with
        ({"args.name": {"starts_with": "Hello"}}, True),
        ({"args.name": {"starts_with": "World"}}, False),
        ({"args.name": {"ends_with": "World"}}, True),
        ({"args.name": {"ends_with": "Hello"}}, False),
        ({"args.amount": {"starts_with": "5"}}, False),
        # exists
        ({"args.path": {"exists": True}}, True),
        ({"args.path": {"exists": False}}, False),
        ({"args.missing": {"exists": False}}, True),
        ({"args.missing": {"exists": True}}, False),
        ({"args.nothing": {"exists": True}}, True),
        ({"args.missing": {"exists": False, "eq": 1}}, False),
        # len
        ({"args.name": {"len_lte": 11}}, True),
        ({"args.name": {"len_lte": 10}}, False),
        ({"args.tags": {"len_gte": 2}}, True),
        ({"args.tags": {"len_gte": 3}}, False),
        ({"args.empty": {"len_lte": 0}}, True),
        ({"args.amount": {"len_lte": 5}}, False),
        ({"args.nested": {"len_gte": 0}}, False),
    ],
)
def test_operators(spec: dict[str, Any], expected: bool) -> None:
    assert holds(spec) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("agent.id", "a1"),
        ("agent.role", "coder"),
        ("agent.depth", 2),
        ("agent.parent_role", "planner"),
        ("agent.on_behalf_of", "u1"),
        ("tool.name", "fs.write"),
        ("tool.namespace", "fs"),
        ("run.id", "r1"),
        ("run.tool_calls", 7),
        ("time.hour_utc", 13),
        ("time.weekday", 2),
        ("args.items.0.name", "first"),
        ("args.items.1.name", "second"),
        ("args.nested.deep.x", 1),
        ("args.tags.1", "b"),
    ],
)
def test_paths_resolve(path: str, expected: object) -> None:
    now = datetime(2030, 1, 2, 13, 5, tzinfo=UTC)  # a Wednesday
    assert holds({path: {"eq": expected}}, run_tool_calls=7, now=now)
    assert not holds({path: {"ne": expected}}, run_tool_calls=7, now=now)


@pytest.mark.parametrize(
    "path",
    ["args.items.5.name", "args.items.x", "args.path.sub", "args.nested.nope", "time.weekday"],
)
def test_missing_paths_are_false_except_exists_false(path: str) -> None:
    assert not holds({path: {"eq": 1}})
    assert not holds({path: {"exists": True}})
    assert holds({path: {"exists": False}})


def test_root_principal_has_no_parent_role() -> None:
    root = Principal(agent_id="r", role="planner", run_id="x")
    context = build_context(root, ToolCall(tool="t"))
    assert compile_condition({"agent.parent_role": {"exists": False}})(context)
    assert compile_condition({"agent.on_behalf_of": {"exists": False}})(context)


def test_mcp_tool_namespace_includes_server() -> None:
    context = build_context(AGENT, ToolCall(tool="mcp:files/read"))
    assert compile_condition({"tool.namespace": {"eq": "mcp:files"}})(context)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"all": [{"args.amount": {"lte": 100}}, {"agent.role": {"eq": "coder"}}]}, True),
        ({"all": [{"args.amount": {"lte": 100}}, {"agent.role": {"eq": "x"}}]}, False),
        ({"any": [{"agent.role": {"eq": "x"}}, {"args.amount": {"eq": 50}}]}, True),
        ({"any": [{"agent.role": {"eq": "x"}}, {"args.amount": {"eq": 1}}]}, False),
        ({"not": {"agent.role": {"eq": "coder"}}}, False),
        ({"not": {"agent.role": {"eq": "x"}}}, True),
        ({"not": {"args.missing": {"eq": 1}}}, True),  # not of a false (missing) is true
        (
            {
                "all": [
                    {"any": [{"args.amount": {"gt": 99}}, {"not": {"args.flag": {"eq": False}}}]}
                ]
            },
            True,
        ),
        ({}, True),
        ({"agent.role": {"eq": "coder"}, "args.amount": {"eq": 50}}, True),
        ({"agent.role": {"eq": "coder"}, "args.amount": {"eq": 1}}, False),
        ({"agent.role": {"eq": "coder"}, "any": [{"args.amount": {"eq": 1}}]}, False),
    ],
)
def test_combinators(spec: dict[str, Any], expected: bool) -> None:
    assert holds(spec) is expected


def test_glob_sees_through_dotdot_in_values() -> None:
    call = ToolCall(tool="t", args={"note": "/workspace/../etc/passwd"})
    context = build_context(AGENT, call)
    assert not compile_condition({"args.note": {"glob": "/workspace/**"}})(context)
    assert compile_condition({"args.note": {"glob": "/etc/**"}})(context)


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ({"args.x": {"lessthan": 1}}, "unknown operator 'lessthan'"),
        ({"args.x": {5: 1}}, "unknown operator '5'"),
        ({"args.x": {}}, "mapping of operator"),
        ({"args.x": 5}, "mapping of operator"),
        ({"args.x": {"lt": "5"}}, "expects a number"),
        ({"args.x": {"lt": True}}, "expects a number"),
        ({"args.x": {"in": "abc"}}, "expects a list"),
        ({"args.x": {"in": [[1]]}}, "expects a list"),
        ({"args.x": {"eq": [1]}}, "expects a scalar"),
        ({"args.x": {"glob": 5}}, "expects a string"),
        ({"args.x": {"regex": "(["}}, "invalid regular expression"),
        ({"args.x": {"regex": "a" * 513}}, "expects a string"),
        ({"args.x": {"regex": 5}}, "expects a string"),
        ({"args.x": {"exists": "yes"}}, "expects a bool"),
        ({"args.x": {"len_lte": -1}}, "expects a int"),
        ({"args.x": {"len_gte": 1.5}}, "expects a int"),
        ({"args.x": {"len_gte": True}}, "expects a int"),
        ({"all": {"a": 1}}, "non-empty list"),
        ({"all": []}, "non-empty list"),
        ({"any": []}, "non-empty list"),
        ({"any": [5]}, "must be a mapping"),
        ({"not": [1]}, "'not' must be a mapping"),
        ({"agnt.role": {"eq": "x"}}, "unknown path 'agnt.role'"),
        ({"agent.nope": {"eq": "x"}}, "unknown path 'agent.nope'"),
        ({"agent": {"eq": "x"}}, "unknown path 'agent'"),
        ({"tool.name.extra": {"eq": "x"}}, "unknown path"),
        ({"args..x": {"eq": 1}}, "invalid condition path"),
        ({"": {"eq": 1}}, "non-empty string"),
        ({1: {"eq": 1}}, "non-empty string"),
    ],
)
def test_invalid_conditions_are_load_errors(spec: dict[Any, Any], fragment: str) -> None:
    with pytest.raises(PolicyError, match=fragment):
        compile_condition(spec)


def test_non_mapping_condition_is_rejected() -> None:
    with pytest.raises(PolicyError):
        compile_condition([1])  # type: ignore[arg-type]


def test_referenced_paths_walks_combinators() -> None:
    spec = {
        "all": [{"time.hour_utc": {"gt": 1}}, {"not": {"args.a": {"eq": 1}}}],
        "any": [{"run.tool_calls": {"lt": 2}}],
    }
    assert referenced_paths(spec) == {"time.hour_utc", "args.a", "run.tool_calls"}


def test_operator_registry_is_documented() -> None:
    assert set(OPERATORS) == {
        "eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "glob", "regex",
        "contains", "starts_with", "ends_with", "exists", "len_lte", "len_gte",
    }  # fmt: skip
    assert all(spec.description and spec.operand for spec in OPERATORS.values())
