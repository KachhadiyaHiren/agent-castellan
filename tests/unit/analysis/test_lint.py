from __future__ import annotations

from agent_castellan.analysis.lint import (
    Finding,
    agents_covered,
    lint_policy,
    reachable_roles,
    tool_pattern_covers,
    tools_covered,
)
from agent_castellan.models import Effect
from agent_castellan.policy.loader import load_policy_text
from agent_castellan.policy.schema import AgentConfig, Defaults, Policy, Rule


def rule(id: str, effect: Effect = Effect.ALLOW, line: int | None = None, **kw: object) -> Rule:
    return Rule.model_validate({"id": id, "effect": effect, "line": line, **kw})


def ids(findings: list[Finding], check: str) -> list[Finding]:
    return [f for f in findings if f.check_id == check]


def pol(*rules: Rule, **kw: object) -> Policy:
    return Policy.model_validate({"rules": rules, **kw})


def test_clean_policy_has_no_findings() -> None:
    p = pol(
        rule("r", tools=("fs.read",), agents=("a",)),
        agents={"a": AgentConfig()},
    )
    assert lint_policy(p) == []


def test_l001_shadowed_allow() -> None:
    p = pol(
        rule("deny-all", Effect.DENY, tools=("fs.*",), line=3),
        rule("allow-read", tools=("fs.read",), line=9),
    )
    (f,) = ids(lint_policy(p), "L001")
    assert (f.rule_id, f.line, f.severity) == ("allow-read", 9, "warning")
    assert "deny-all" in f.message


def test_l001_later_deny_also_shadows() -> None:
    p = pol(rule("a", tools=("x.y",)), rule("d", Effect.DENY, tools=("*",)))
    assert ids(lint_policy(p), "L001")


def test_l001_not_shadowed_when_deny_has_condition_or_narrower() -> None:
    cond = rule("d", Effect.DENY, tools=("*",), when={"args.x": {"eq": 1}})
    narrow = rule("d2", Effect.DENY, tools=("fs.read",), agents=("coder",))
    p = pol(
        cond, narrow, rule("a", tools=("fs.read",)), rule("ask", Effect.ASK, tools=("fs.read",))
    )
    assert ids(lint_policy(p), "L001") == []


def test_l002_duplicate_ids() -> None:
    p = pol(rule("x", tools=("a",)), rule("x", tools=("b",), line=7))
    (f,) = ids(lint_policy(p), "L002")
    assert (f.severity, f.line, f.rule_id) == ("error", 7, "x")


def test_l003_wildcard_allow() -> None:
    p = pol(rule("w", tools=("*",)), rule("ok", tools=("*",), when={"a.b": {"eq": 1}}))
    (f,) = ids(lint_policy(p), "L003")
    assert f.rule_id == "w"


def test_l004_undefined_roles() -> None:
    p = pol(
        rule("r", Effect.ASK, agents=("ghost", "*", "g*"), approver="role:phantom", line=4),
        agents={"a": AgentConfig(can_delegate_to=("nope",))},
    )
    msgs = [f.message for f in ids(lint_policy(p), "L004")]
    assert len(msgs) == 3
    assert any("ghost" in m for m in msgs)
    assert any("phantom" in m for m in msgs)
    assert any("nope" in m for m in msgs)


def test_l005_and_l006_delegation_graph() -> None:
    p = pol(
        rule("r", Effect.ASK, approver="role:reviewer", line=2),
        agents={
            "planner": AgentConfig(can_delegate_to=("coder",)),
            "coder": AgentConfig(),
            "reviewer": AgentConfig(),
        },
    )
    findings = lint_policy(p)
    assert [f.rule_id for f in ids(findings, "L005")] == ["r"]
    assert "reviewer" in ids(findings, "L006")[0].message
    assert len(ids(findings, "L006")) == 1


def test_l005_ok_when_approver_is_root_or_delegate() -> None:
    p = pol(
        rule("a", Effect.ASK, approver="role:planner"),
        rule("b", Effect.ASK, approver="role:coder"),
        rule("c", Effect.ASK, approver="human"),
        agents={"planner": AgentConfig(can_delegate_to=("coder",)), "coder": AgentConfig()},
    )
    findings = lint_policy(p)
    assert ids(findings, "L005") == []
    assert ids(findings, "L006") == []


def test_no_delegation_means_no_l005_l006() -> None:
    p = pol(rule("a", Effect.ASK, approver="role:x"), agents={"x": AgentConfig()})
    findings = lint_policy(p)
    assert ids(findings, "L005") == []
    assert ids(findings, "L006") == []


def test_l007_default_allow() -> None:
    (f,) = ids(lint_policy(Policy(defaults=Defaults(effect=Effect.ALLOW))), "L007")
    assert f.severity == "warning"
    assert f.rule_id is None
    assert ids(lint_policy(Policy()), "L007") == []


def test_reachable_roles_cycle_without_root() -> None:
    assert reachable_roles({"a": ("b",), "b": ("a",)}) == set()
    assert reachable_roles({"p": ("c",), "c": ("d",), "d": ()}) == {"p", "c", "d"}


def test_tool_pattern_covers_table() -> None:
    table = [
        ("*", "anything.at.all", True),
        ("**", "a.*", True),
        ("fs.read", "fs.read", True),
        ("FS.read", "fs.READ", True),
        ("fs.*", "fs.read", True),
        ("fs.*", "fs.a.b", False),
        ("fs.**", "fs.a.b", True),
        ("fs.**", "fs.a.*", True),
        ("fs.*", "fs.re*", True),
        ("fs.*", "fs.**", False),
        ("fs.*", "other.*", False),
        ("fs.read", "fs.*", False),
        ("a*.b", "ab.*", False),
        ("fs.write", "fs.read", False),
    ]
    for outer, inner, expected in table:
        assert tool_pattern_covers(outer, inner) is expected, (outer, inner)


def test_glob_question_mark_and_helpers() -> None:
    assert tool_pattern_covers("fs.rea?", "fs.read")
    assert tools_covered(["fs.*", "web.*"], ["fs.read", "web.get"])
    assert not tools_covered(["fs.*"], ["fs.read", "web.get"])
    assert agents_covered([], ["a"])
    assert agents_covered(["*"], ["a"])
    assert agents_covered(["a", "b"], ["a"])
    assert not agents_covered(["a"], ["*"])
    assert not agents_covered(["a"], [])
    assert not agents_covered(["a"], ["b"])


def test_l008_unused_role_flagged_with_line() -> None:
    p = load_policy_text(
        "version: 1\n"
        "agents:\n"
        "  coder: {}\n"
        "  stale: {}\n"
        "rules:\n"
        "  - id: read\n"
        "    agents: [coder]\n"
        "    tools: [fs.read]\n"
        "    effect: allow\n"
    )
    (f,) = ids(lint_policy(p), "L008")
    assert (f.severity, f.line, f.rule_id) == ("warning", 4, None)
    assert "stale" in f.message


def test_l008_quiet_when_role_used_by_rule_approver_or_delegation() -> None:
    p = pol(
        rule("allow-coder", tools=("fs.read",), agents=("coder",)),
        rule("ask-review", Effect.ASK, tools=("fs.write",), approver="role:reviewer"),
        agents={
            "coder": AgentConfig(can_delegate_to=("helper",)),
            "reviewer": AgentConfig(),
            "helper": AgentConfig(),
        },
    )
    assert ids(lint_policy(p), "L008") == []
