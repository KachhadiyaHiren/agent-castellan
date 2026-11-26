"""Loader: valid documents, schema validation and line-numbered errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.models import Effect
from agent_castellan.policy.loader import load_policy, load_policy_text

FULL = """\
version: 1

defaults:
  effect: deny

agents:
  planner:
    can_delegate_to: [researcher, coder]
    max_delegation_depth: 2
  researcher: {}
  coder:
  reviewer: {}

rules:
  - id: no-secrets
    description: Never touch secret files
    tools: ["*"]
    when:
      any:
        - args.path: { glob: "**/.env*" }
        - args.path: { glob: "**/*.pem" }
    effect: deny
    reason: Secret files are off limits

  - id: write-needs-review
    agents: [coder]
    tools: ["fs.write", "fs.delete"]
    when:
      args.path: { glob: "/workspace/**" }
    effect: ask
    approver: role:reviewer
    priority: 5

  - id: small-payments-only
    tools: ["payments.*"]
    when:
      all:
        - args.amount: { lte: 100 }
        - args.currency: { in: [USD, EUR] }
    effect: ask
    approver: human

budgets:
  run:
    max_tool_calls: 200
    max_cost_units: 500
  per_role:
    researcher: { max_tool_calls: 80 }

approvals:
  ttl_seconds: 300

audit:
  path: ./audit.jsonl
"""


def test_full_policy_loads() -> None:
    policy = load_policy_text(FULL, source="team.yaml")
    assert policy.version == 1
    assert policy.source == "team.yaml"
    assert policy.defaults.effect is Effect.DENY
    assert policy.agents["planner"].can_delegate_to == ("researcher", "coder")
    assert policy.agents["planner"].max_delegation_depth == 2
    assert policy.agents["coder"].can_delegate_to == ()
    assert [r.id for r in policy.rules] == [
        "no-secrets",
        "write-needs-review",
        "small-payments-only",
    ]
    assert policy.rules[1].approver == "role:reviewer"
    assert policy.rules[1].priority == 5
    assert policy.rules[0].agents == ("*",)
    assert policy.rules[0].when == {
        "any": [{"args.path": {"glob": "**/.env*"}}, {"args.path": {"glob": "**/*.pem"}}]
    }
    assert policy.budgets.run.max_tool_calls == 200
    assert policy.budgets.run.max_cost_units == 500
    assert policy.budgets.per_role["researcher"].max_tool_calls == 80
    assert policy.approvals.ttl_seconds == 300
    assert policy.audit.path == "./audit.jsonl"


def test_rules_record_their_line_numbers() -> None:
    policy = load_policy_text(FULL)
    assert [r.line for r in policy.rules] == [15, 25, 34]


def test_minimal_policy_uses_defaults() -> None:
    policy = load_policy_text("version: 1\n")
    assert policy.rules == ()
    assert policy.defaults.effect is Effect.DENY
    assert policy.approvals.ttl_seconds == 600


def test_load_policy_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(FULL, encoding="utf-8")
    policy = load_policy(path)
    assert policy.source == str(path)
    assert load_policy(str(path)).rules == policy.rules


def test_missing_file_is_a_policy_error(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="cannot read policy file"):
        load_policy(tmp_path / "nope.yaml")


def test_undecodable_file_is_a_policy_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(PolicyError, match="cannot read policy file"):
        load_policy(path)


def err(text: str) -> PolicyError:
    with pytest.raises(PolicyError) as info:
        load_policy_text(text, source="team.yaml")
    return info.value


def test_unknown_operator_error_has_file_line_and_rule() -> None:
    error = err(
        "version: 1\n"
        "rules:\n"
        "  - id: write-needs-review\n"
        "    tools: [fs.write]\n"
        "    when:\n"
        "      args.n: {lessthan: 1}\n"
        "    effect: ask\n"
    )
    assert error.file == "team.yaml"
    assert error.line == 5
    assert error.rule_id == "write-needs-review"
    assert str(error).startswith(
        "team.yaml:5 rule 'write-needs-review': unknown operator 'lessthan'"
    )


def test_nested_bad_condition_is_reported_on_the_when_line() -> None:
    error = err(
        "rules:\n  - id: r\n    effect: allow\n    when:\n      all:\n"
        "        - args.x: {regex: '(['}\n"
    )
    assert (error.line, error.rule_id) == (4, "r")
    assert "invalid regular expression" in error.message


def test_bad_tool_pattern_is_reported() -> None:
    error = err("rules:\n  - id: r\n    effect: allow\n    tools: ['fs.read', ' ']\n")
    assert error.rule_id == "r"
    assert error.line == 4


@pytest.mark.parametrize(
    ("text", "line", "fragment"),
    [
        ("version: 2\n", 1, "version"),
        ("version: 1\nwhat: 1\n", 2, "unknown key 'what'"),
        ("defaults:\n  effect: maybe\n", 2, "defaults.effect"),
        ("defaults:\n  effect: deny\n  extra: 1\n", 3, "unknown key 'extra'"),
        ("agents:\n  a:\n    can_delegate_to: nope\n", 3, "can_delegate_to"),
        ("agents:\n  a:\n    max_delegation_depth: -1\n", 3, "max_delegation_depth"),
        ("approvals:\n  ttl_seconds: 0\n", 2, "ttl_seconds"),
        ("budgets:\n  run:\n    max_tool_calls: -5\n", 3, "max_tool_calls"),
        ("rules:\n  - id: a\n    effect: allow\n    approver: bob\n", 4, "approver"),
        ("rules:\n  - id: a\n    effect: allow\n    approver: 'role:'\n", 4, "approver"),
        ("rules:\n  - id: ' '\n    effect: allow\n", 2, "blank"),
        ("rules:\n  - id: a\n    effect: allow\n    tools: []\n", 4, "non-empty"),
        ("rules:\n  - id: a\n    effect: allow\n    agents: ['']\n", 4, "non-empty"),
        ("rules:\n  - id: a\n    effect: allow\n    tool: x\n", 4, "unknown key 'tool'"),
        ("rules:\n  - id: a\n    effect: allow\n    line: 3\n", 4, "unknown key 'line'"),
        ("rules:\n  - id: a\n", 2, "effect"),
        ("rules:\n  - id: a\n    effect: permit\n", 3, "effect"),
        ("rules: nope\n", 1, "rules"),
        ("rules:\n  - nope\n", 2, "rules.0"),
    ],
)
def test_schema_errors_point_at_the_line(text: str, line: int, fragment: str) -> None:
    error = err(text)
    assert error.line == line
    assert fragment in error.message


def test_schema_error_inside_a_rule_names_the_rule() -> None:
    error = err("rules:\n  - id: abc\n    effect: allow\n    priority: high\n")
    assert error.rule_id == "abc"
    assert error.line == 4


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "just a string\n", "42\n"])
def test_non_mapping_documents_are_rejected(text: str) -> None:
    assert "must be a mapping" in err(text).message


def test_yaml_syntax_error_has_line() -> None:
    error = err("version: 1\nrules: [unclosed\nagents: {}\n")
    assert error.file == "team.yaml"
    assert error.line is not None


def test_duplicate_keys_are_rejected() -> None:
    error = err("version: 1\nversion: 1\n")
    assert error.line == 2


def test_duplicate_rule_ids_still_load_so_lint_can_report_them() -> None:
    policy = load_policy_text("rules:\n  - id: a\n    effect: allow\n  - id: a\n    effect: deny\n")
    assert [r.id for r in policy.rules] == ["a", "a"]


def test_yaml_scalars_become_plain_python_values() -> None:
    policy = load_policy_text(
        "rules:\n  - id: a\n    effect: allow\n    when:\n"
        "      args.n: {eq: 1.5}\n      args.m: {in: [1, true, x]}\n      args.k: {eq: 0x10}\n"
    )
    assert policy.rules[0].when == {
        "args.n": {"eq": 1.5},
        "args.m": {"in": [1, True, "x"]},
        "args.k": {"eq": 16},
    }
    assert type(policy.rules[0].when["args.n"]["eq"]) is float  # type: ignore[index]
