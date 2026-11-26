"""`castellan lint` with text, json and github output."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.analysis import lint as lint_mod
from agent_castellan.errors import PolicyError
from agent_castellan.policy import loader as loader_mod
from agent_castellan.policy.schema import Policy

Invoke = Callable[..., Any]

ERROR = lint_mod.Finding("L001", "error", "rule 'a' is shadowed", rule_id="a", line=7)
WARN = lint_mod.Finding("L007", "warning", "defaults allow\nsecond line 100%")


@pytest.fixture
def findings(monkeypatch: pytest.MonkeyPatch, fake_policy: list[Path]) -> list[lint_mod.Finding]:
    items: list[lint_mod.Finding] = []
    monkeypatch.setattr(lint_mod, "lint_policy", lambda policy: list(items))
    return items


def test_text_format_clean(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    result = invoke("lint", str(policy_file))
    assert result.exit_code == 0
    assert "no issues found" in result.output


def test_text_format_lists_findings_and_fails_on_error(
    invoke: Invoke, findings: list[Any], policy_file: Path
) -> None:
    findings.extend([ERROR, lint_mod.Finding("L003", "warning", "wide", rule_id="b")])
    result = invoke("lint", str(policy_file))
    assert result.exit_code == 1
    assert f"{policy_file}:7: error L001 rule 'a' is shadowed [a]" in result.output
    assert f"{policy_file}: warning L003 wide [b]" in result.output


def test_warnings_alone_exit_zero(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    findings.append(WARN)
    result = invoke("lint", str(policy_file))
    assert result.exit_code == 0


def test_json_format(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    findings.extend([ERROR, WARN])
    result = invoke("lint", str(policy_file), "--format", "json")
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data[0] == {
        "check_id": "L001",
        "severity": "error",
        "message": "rule 'a' is shadowed",
        "rule_id": "a",
        "line": 7,
    }
    assert data[1]["check_id"] == "L007"


def test_json_format_empty(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    result = invoke("lint", str(policy_file), "--format", "json")
    assert json.loads(result.output) == []


def test_github_format(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    findings.extend([ERROR, WARN])
    result = invoke("lint", str(policy_file), "--format", "github")
    lines = result.output.splitlines()
    assert lines[0] == f"::error file={policy_file},line=7,title=L001::rule 'a' is shadowed"
    assert lines[1] == (
        f"::warning file={policy_file},title=L007::defaults allow%0Asecond line 100%25"
    )


def test_bad_format_value(invoke: Invoke, findings: list[Any], policy_file: Path) -> None:
    result = invoke("lint", str(policy_file), "--format", "xml")
    assert result.exit_code != 0


def test_load_error(invoke: Invoke, monkeypatch: pytest.MonkeyPatch, policy_file: Path) -> None:
    def boom(path: str | Path) -> Policy:
        raise PolicyError("bad yaml", file="p.yaml", line=1)

    monkeypatch.setattr(loader_mod, "load_policy", boom)
    result = invoke("lint", str(policy_file))
    assert result.exit_code == 3
    assert "p.yaml:1 bad yaml" in result.output


@pytest.mark.parametrize(
    ("exc", "text"),
    [(NotImplementedError(), "not implemented"), (PolicyError("broken"), "broken")],
)
def test_linter_failures(
    invoke: Invoke,
    monkeypatch: pytest.MonkeyPatch,
    fake_policy: list[Path],
    policy_file: Path,
    exc: Exception,
    text: str,
) -> None:
    def boom(policy: Policy) -> list[Any]:
        raise exc

    monkeypatch.setattr(lint_mod, "lint_policy", boom)
    result = invoke("lint", str(policy_file))
    assert result.exit_code == 3
    assert text in result.output
