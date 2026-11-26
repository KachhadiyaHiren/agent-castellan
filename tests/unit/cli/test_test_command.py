"""`castellan test`: policy test files with pytest-like output and JUnit export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.policy import loader as loader_mod

Invoke = Callable[..., Any]

PASSING = """\
policy: ../team.yaml
cases:
  - name: coder can read
    agent: { role: coder, depth: 1 }
    call: { tool: fs.read, args: { path: /workspace/a } }
    expect: allow
    expect_rule: read-ok
  - name: coder write needs approval
    agent: { role: coder }
    call: { tool: fs.write }
    expect: ask
"""

FAILING = """\
policy: team.yaml
cases:
  - name: wrongly expects allow
    agent: { role: coder }
    call: { tool: fs.delete }
    expect: allow
  - name: wrong rule
    agent: { role: coder }
    call: { tool: fs.read }
    expect: allow
    expect_rule: other-rule
  - name: fine
    agent: { role: coder }
    call: { tool: fs.read }
    expect: allow
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_all_passing(invoke: Invoke, fake_policy: list[Path], tmp_path: Path) -> None:
    f = write(tmp_path, "ok.test.yaml", PASSING)
    result = invoke("test", str(f))
    assert result.exit_code == 0
    assert f"{f} .." in result.output
    assert "2 passed" in result.output
    assert fake_policy == [tmp_path / "../team.yaml"]


def test_failures_listed_and_exit_nonzero(
    invoke: Invoke, fake_policy: list[Path], tmp_path: Path
) -> None:
    f = write(tmp_path, "bad.test.yaml", FAILING)
    result = invoke("test", str(f))
    assert result.exit_code == 1
    assert f"{f} FF." in result.output
    assert "FAILED" in result.output
    assert "expected allow, got deny (rule: no-delete" in result.output
    assert "expected rule other-rule, got read-ok" in result.output
    assert "1 passed, 2 failed" in result.output


def test_unmatched_default_reports_rule_none(
    invoke: Invoke, fake_policy: list[Path], tmp_path: Path
) -> None:
    text = PASSING.replace("fs.write", "net.get").replace("expect: ask", "expect: allow")
    result = invoke("test", str(write(tmp_path, "t.yaml", text)))
    assert "rule: none" in result.output


def test_multiple_files_and_junit(invoke: Invoke, fake_policy: list[Path], tmp_path: Path) -> None:
    good = write(tmp_path, "good.test.yaml", PASSING)
    bad = write(tmp_path, "bad.test.yaml", FAILING)
    out = tmp_path / "report.xml"
    result = invoke("test", str(good), str(bad), "--junit", str(out))
    assert result.exit_code == 1
    suite = ET.parse(out).getroot()  # noqa: S314
    assert suite.tag == "testsuite"
    assert suite.get("tests") == "5"
    assert suite.get("failures") == "2"
    assert suite.get("errors") == "0"
    cases = suite.findall("testcase")
    assert len(cases) == 5
    failures = [c for c in cases if c.find("failure") is not None]
    assert {c.get("name") for c in failures} == {"wrongly expects allow", "wrong rule"}


def test_unreadable_files_are_errors(
    invoke: Invoke, fake_policy: list[Path], tmp_path: Path
) -> None:
    result = invoke("test", str(tmp_path / "missing.yaml"))
    assert result.exit_code == 1
    assert "ERROR" in result.output
    assert "1 error" in result.output


@pytest.mark.parametrize(
    "text",
    [
        "policy: [unclosed",
        "policy: p.yaml\ncases:\n  - name: x\n    agent: {role: a}\n    call: {tool: t}\n"
        "    expect: maybe\n",
        "policy: p.yaml\ncases: []\nextra: 1\n",
    ],
)
def test_invalid_test_file_is_error_and_junit_records_it(
    invoke: Invoke, fake_policy: list[Path], tmp_path: Path, text: str
) -> None:
    out = tmp_path / "r.xml"
    result = invoke("test", str(write(tmp_path, "x.yaml", text)), "--junit", str(out))
    assert result.exit_code == 1
    assert "1 error" in result.output
    suite = ET.parse(out).getroot()  # noqa: S314
    assert suite.get("errors") == "1"
    assert suite.find("testcase/error") is not None


def test_policy_load_error_is_reported(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(path: str | Path) -> None:
        raise PolicyError("unknown operator", file="team.yaml", line=3)

    monkeypatch.setattr(loader_mod, "load_policy", boom)
    result = invoke("test", str(write(tmp_path, "t.yaml", PASSING)))
    assert result.exit_code == 1
    assert "team.yaml:3 unknown operator" in result.output


def test_unimplemented_loader_is_reported(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def stub(path: str | Path) -> None:
        raise NotImplementedError

    monkeypatch.setattr(loader_mod, "load_policy", stub)
    result = invoke("test", str(write(tmp_path, "t.yaml", PASSING)))
    assert result.exit_code == 1
    assert "not implemented" in result.output
