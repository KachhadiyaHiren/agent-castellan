# ruff: noqa: RUF001
"""PolicyEngine: every step of the decision algorithm (PLAN.md §2) plus delegation rules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.interfaces import PolicyDecider
from agent_castellan.models import Decision, Effect, Principal, ToolCall
from agent_castellan.policy.engine import PolicyEngine
from agent_castellan.policy.loader import load_policy_text
from agent_castellan.testing.fakes import FrozenClock

CODER = Principal(agent_id="c1", role="coder", run_id="r1", depth=1, parent_role="planner")
RESEARCHER = Principal(agent_id="s1", role="researcher", run_id="r1", depth=2)


def engine(rules: str, defaults: str = "deny", **kw: Any) -> PolicyEngine:
    text = f"version: 1\ndefaults:\n  effect: {defaults}\nrules:\n{rules}"
    return PolicyEngine(load_policy_text(text, source="t.yaml"), **kw)


def call(tool: str = "fs.read", **args: Any) -> ToolCall:
    return ToolCall(tool=tool, args=args)


def test_engine_satisfies_the_decider_protocol() -> None:
    decider: PolicyDecider = engine("  - {id: a, effect: allow}\n")
    assert isinstance(decider.decide(CODER, call()), Decision)


# --- steps 2-6: collecting matches and choosing the effect ----------------------------


def test_allow_rule_allows() -> None:
    d = engine("  - {id: a, tools: [fs.read], effect: allow, reason: ok}\n").decide(CODER, call())
    assert (d.effect, d.rule_id, d.source, d.reason) == (Effect.ALLOW, "a", "policy", "ok")


def test_ask_rule_asks() -> None:
    d = engine("  - {id: a, tools: [fs.read], effect: ask}\n").decide(CODER, call())
    assert (d.effect, d.rule_id) == (Effect.ASK, "a")


def test_deny_rule_denies_with_its_reason() -> None:
    d = engine("  - {id: a, effect: deny, reason: nope}\n", defaults="allow").decide(CODER, call())
    assert (d.effect, d.reason) == (Effect.DENY, "nope")


def test_reason_defaults_to_naming_the_rule() -> None:
    d = engine("  - {id: a, effect: allow}\n").decide(CODER, call())
    assert "'a'" in d.reason


def test_deny_rule_overrides_higher_priority_allow() -> None:
    d = engine(
        "  - {id: allow-it, effect: allow, priority: 100}\n"
        "  - {id: deny-it, effect: deny, priority: 0}\n"
    ).decide(CODER, call())
    assert (d.effect, d.rule_id) == (Effect.DENY, "deny-it")


def test_deny_overrides_ask_and_allow_regardless_of_order() -> None:
    d = engine(
        "  - {id: x, effect: allow}\n  - {id: y, effect: ask}\n  - {id: z, effect: deny}\n"
    ).decide(CODER, call())
    assert d.effect is Effect.DENY


def test_ask_overrides_allow() -> None:
    d = engine("  - {id: x, effect: allow, priority: 9}\n  - {id: y, effect: ask}\n").decide(
        CODER, call()
    )
    assert (d.effect, d.rule_id) == (Effect.ASK, "y")


@pytest.mark.parametrize(
    ("default", "effect"), [("deny", Effect.DENY), ("ask", Effect.ASK), ("allow", Effect.ALLOW)]
)
def test_no_matching_rule_uses_the_default(default: str, effect: Effect) -> None:
    d = engine("  - {id: x, tools: [other.tool], effect: allow}\n", defaults=default).decide(
        CODER, call()
    )
    assert (d.effect, d.rule_id, d.source) == (effect, None, "default")
    assert default in d.reason


def test_policy_without_rules_uses_the_default() -> None:
    d = PolicyEngine(load_policy_text("version: 1\n")).decide(CODER, call())
    assert (d.effect, d.source) == (Effect.DENY, "default")


# --- step 7: priority then file order ------------------------------------------------


def test_highest_priority_rule_id_wins_within_the_effect() -> None:
    d = engine(
        "  - {id: low, effect: allow, priority: 1}\n  - {id: high, effect: allow, priority: 5}\n"
        "  - {id: mid, effect: allow, priority: 3}\n"
    ).decide(CODER, call())
    assert d.rule_id == "high"


def test_equal_priority_prefers_earliest_in_file() -> None:
    d = engine("  - {id: first, effect: deny}\n  - {id: second, effect: deny}\n").decide(
        CODER, call()
    )
    assert d.rule_id == "first"


def test_negative_priority_still_matches() -> None:
    d = engine("  - {id: a, effect: allow, priority: -5}\n").decide(CODER, call())
    assert d.rule_id == "a"


# --- matching: agents, tools, when ---------------------------------------------------


def test_agents_filter_by_role() -> None:
    e = engine("  - {id: a, agents: [coder], effect: allow}\n")
    assert e.decide(CODER, call()).effect is Effect.ALLOW
    assert e.decide(RESEARCHER, call()).effect is Effect.DENY


def test_agents_star_matches_every_role() -> None:
    e = engine("  - {id: a, agents: ['*'], effect: allow}\n")
    assert e.decide(RESEARCHER, call()).effect is Effect.ALLOW


def test_tools_use_globs_on_the_normalized_name() -> None:
    e = engine("  - {id: a, tools: ['fs.*'], effect: allow}\n")
    assert e.decide(CODER, call("FS.Read")).effect is Effect.ALLOW
    assert e.decide(CODER, call("fs.a.b")).effect is Effect.DENY
    assert e.decide(CODER, call("web.fetch")).effect is Effect.DENY


def test_when_conditions_filter() -> None:
    e = engine(
        "  - id: a\n    tools: ['fs.*']\n    effect: allow\n    when:\n"
        "      args.path: {glob: '/workspace/**'}\n"
    )
    assert e.decide(CODER, call(path="/workspace/a.py")).effect is Effect.ALLOW
    assert e.decide(CODER, call(path="/etc/passwd")).effect is Effect.DENY
    assert e.decide(CODER, call()).effect is Effect.DENY  # missing path never matches


def test_conditions_can_use_agent_attributes() -> None:
    e = engine(
        "  - id: a\n    effect: allow\n    when:\n      agent.depth: {lte: 1}\n"
        "      agent.parent_role: {eq: planner}\n"
    )
    assert e.decide(CODER, call()).effect is Effect.ALLOW
    assert e.decide(RESEARCHER, call()).effect is Effect.DENY


# --- trace -----------------------------------------------------------------------------


def test_trace_has_one_step_per_rule_in_file_order() -> None:
    d = engine(
        "  - {id: wrong-role, agents: [reviewer], effect: allow}\n"
        "  - {id: wrong-tool, tools: [web.fetch], effect: allow}\n"
        "  - id: wrong-when\n    effect: allow\n    when: {args.x: {eq: 1}}\n"
        "  - {id: hit, effect: allow}\n"
    ).decide(CODER, call(x=2))
    assert [(s.rule_id, s.matched) for s in d.trace] == [
        ("wrong-role", False),
        ("wrong-tool", False),
        ("wrong-when", False),
        ("hit", True),
    ]
    details = [s.detail for s in d.trace]
    assert "role 'coder'" in details[0]
    assert details[1] == "tools: no match for 'fs.read'"
    assert details[2].startswith("when:")
    assert details[3] == "matched"


def test_trace_is_present_for_default_decisions() -> None:
    d = engine("  - {id: x, tools: [other], effect: allow}\n").decide(CODER, call())
    assert len(d.trace) == 1
    assert d.trace[0].matched is False


def test_trace_lists_every_matching_rule_not_just_the_winner() -> None:
    d = engine("  - {id: a, effect: allow}\n  - {id: b, effect: deny}\n").decide(CODER, call())
    assert [s.matched for s in d.trace] == [True, True]


# --- step 1: invalid calls ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        ToolCall(tool=""),
        ToolCall(tool="fs.read", args={"path": "/../etc/passwd"}),
        ToolCall(tool="fs.read", args={"path": "/a\x00b"}),
        ToolCall(tool="fs\x00.read"),
    ],
)
def test_invalid_calls_are_denied_even_when_everything_is_allowed(bad: ToolCall) -> None:
    d = engine("  - {id: a, effect: allow}\n", defaults="allow").decide(CODER, bad)
    assert (d.effect, d.reason, d.source, d.rule_id) == (
        Effect.DENY,
        "invalid_call",
        "invalid",
        None,
    )
    assert d.trace[0].matched is False
    assert d.trace[0].detail


# --- normalization really protects the rules ----------------------------------------------


E = (
    "  - id: sandbox\n    tools: ['fs.*']\n    effect: allow\n    when:\n"
    "      args.path: {glob: '/workspace/**'}\n"
    "  - id: no-secrets\n    effect: deny\n    when:\n      args.path: {glob: '**/.env*'}\n"
)


@pytest.mark.parametrize(
    ("tool", "path", "effect"),
    [
        ("fs.read", "/workspace/app.py", Effect.ALLOW),
        ("fs.read", "/workspace/../etc/passwd", Effect.DENY),
        ("fs.read", "/workspace/a/../../etc/passwd", Effect.DENY),
        ("fs.read", "/workspace/./sub//file", Effect.ALLOW),
        ("fs.read", "//workspace/file", Effect.ALLOW),
        ("fs.read", "/workspace/a/../.env", Effect.DENY),
        ("fs.read", "/workspace/.env", Effect.DENY),
        ("fs.read", "/workspace/sub/.env.local", Effect.DENY),
        ("FS.READ", "/workspace/x", Effect.ALLOW),
        ("Fs.Read", "/workspace/.env", Effect.DENY),
        ("ｆｓ.read", "/workspace/x", Effect.ALLOW),
        ("fs.read", "/workspace/../../../etc/passwd", Effect.DENY),
        ("fs.read", "/workspace\x00/../etc/passwd", Effect.DENY),
    ],
)
def test_path_tricks_cannot_escape_the_sandbox(tool: str, path: str, effect: Effect) -> None:
    assert engine(E).decide(CODER, call(tool, path=path)).effect is effect


# --- context: time and run counters --------------------------------------------------------


def test_time_conditions_use_the_injected_clock() -> None:
    e = engine(
        "  - id: office\n    effect: allow\n    when:\n      time.hour_utc: {gte: 9, lt: 17}\n"
        "      time.weekday: {lt: 5}\n",
        clock=FrozenClock(datetime(2030, 1, 2, 10, tzinfo=UTC)),  # Wednesday 10:00
    )
    assert e.decide(CODER, call()).effect is Effect.ALLOW
    late = engine(
        "  - id: office\n    effect: allow\n    when:\n      time.hour_utc: {gte: 9, lt: 17}\n",
        clock=FrozenClock(datetime(2030, 1, 2, 23, tzinfo=UTC)),
    )
    assert late.decide(CODER, call()).effect is Effect.DENY


def test_time_conditions_work_with_the_system_clock_by_default() -> None:
    e = engine("  - id: any\n    effect: allow\n    when:\n      time.hour_utc: {gte: 0}\n")
    assert e.decide(CODER, call()).effect is Effect.ALLOW


def test_run_tool_calls_come_from_the_injected_counter() -> None:
    counts = {"r1": 3}
    e = engine(
        "  - id: few\n    effect: allow\n    when:\n      run.tool_calls: {lt: 5}\n",
        run_tool_calls=lambda run_id: counts[run_id],
    )
    assert e.decide(CODER, call()).effect is Effect.ALLOW
    counts["r1"] = 5
    assert e.decide(CODER, call()).effect is Effect.DENY


def test_run_tool_calls_default_to_zero_without_a_counter() -> None:
    e = engine("  - id: few\n    effect: allow\n    when:\n      run.tool_calls: {eq: 0}\n")
    assert e.decide(CODER, call()).effect is Effect.ALLOW


# --- approver_for -----------------------------------------------------------------------------


def test_approver_for_returns_the_rule_approver() -> None:
    e = engine(
        "  - {id: a, effect: ask, approver: 'role:reviewer'}\n"
        "  - {id: b, effect: ask}\n  - {id: c, effect: ask, approver: 'agent:x1'}\n"
    )
    assert e.approver_for("a") == "role:reviewer"
    assert e.approver_for("b") == "human"
    assert e.approver_for("c") == "agent:x1"


def test_approver_for_unknown_rule_is_an_error() -> None:
    with pytest.raises(PolicyError, match="unknown rule 'zzz'"):
        engine("  - {id: a, effect: ask}\n").approver_for("zzz")


# --- can_delegate ---


DELEGATION = """\
version: 1
agents:
  planner:
    can_delegate_to: [researcher, coder]
    max_delegation_depth: 2
  lead:
    can_delegate_to: [coder]
  researcher: {}
  coder: {}
"""


@pytest.mark.parametrize(
    ("parent", "child", "depth", "expected"),
    [
        ("planner", "researcher", 0, True),
        ("planner", "coder", 0, True),
        ("planner", "coder", 1, True),  # child would be at depth 2 == max
        ("planner", "coder", 2, False),  # child would be at depth 3 > max
        ("planner", "reviewer", 0, False),  # not listed
        ("lead", "coder", 0, True),
        ("lead", "coder", 50, True),  # no depth limit configured
        ("lead", "researcher", 0, False),
        ("researcher", "coder", 0, False),  # empty can_delegate_to
        ("ghost", "coder", 0, False),  # role not defined
    ],
)
def test_can_delegate(parent: str, child: str, depth: int, expected: bool) -> None:
    e = PolicyEngine(load_policy_text(DELEGATION))
    assert e.can_delegate(parent, child, depth) is expected


# --- construction errors -------------------------------------------------------------------------


def test_invalid_rules_in_a_hand_built_policy_raise_policy_error_with_context() -> None:
    from agent_castellan.policy.schema import Policy, Rule

    policy = Policy(
        rules=(Rule(id="bad", effect=Effect.ALLOW, when={"args.x": {"nope": 1}}, line=7),),
        source="built.yaml",
    )
    with pytest.raises(PolicyError, match=r"built.yaml:7 rule 'bad': unknown operator 'nope'"):
        PolicyEngine(policy)


def test_decide_does_not_mutate_the_policy_or_call() -> None:
    e = engine(E)
    original = ToolCall(tool="FS.Read", args={"path": "/workspace/../etc/x"})
    e.decide(CODER, original)
    assert original.tool == "FS.Read"
    assert original.args == {"path": "/workspace/../etc/x"}
