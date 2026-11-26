"""`castellan check` and `castellan explain`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.policy import loader as loader_mod

Invoke = Callable[..., Any]


@pytest.mark.parametrize(
    ("tool", "code", "word"),
    [("fs.read", 0, "ALLOW"), ("fs.delete", 1, "DENY"), ("fs.write", 2, "ASK")],
)
def test_check_exit_code_follows_decision(
    invoke: Invoke, fake_policy: list[Path], policy_file: Path, tool: str, code: int, word: str
) -> None:
    result = invoke("check", str(policy_file), "--role", "coder", "--tool", tool)
    assert result.exit_code == code
    assert result.output.startswith(word)
    assert fake_policy == [policy_file]


def test_check_prints_rule_and_reason(
    invoke: Invoke, fake_policy: list[Path], policy_file: Path
) -> None:
    result = invoke(
        "check", str(policy_file), "--role", "coder", "--tool", "fs.read",
        "--args", '{"path": "/workspace/a"}', "--depth", "1",
        "--parent-role", "planner", "--on-behalf-of", "alice",
    )  # fmt: skip
    assert "rule=read-ok" in result.output
    assert "reason=fake" in result.output


def test_check_unlisted_tool_shows_default(
    invoke: Invoke, fake_policy: list[Path], policy_file: Path
) -> None:
    result = invoke("check", str(policy_file), "--role", "coder", "--tool", "net.get")
    assert result.exit_code == 1
    assert "rule=-" in result.output


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]"])
def test_check_rejects_bad_args(
    invoke: Invoke, fake_policy: list[Path], policy_file: Path, bad: str
) -> None:
    result = invoke("check", str(policy_file), "--role", "r", "--tool", "fs.read", "--args", bad)
    assert result.exit_code == 3
    assert "--args" in result.output


def test_check_reports_policy_error(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    def boom(path: str | Path) -> None:
        raise PolicyError("unknown operator 'lessthan'", file="team.yaml", line=42, rule_id="r1")

    monkeypatch.setattr(loader_mod, "load_policy", boom)
    result = invoke("check", str(policy_file), "--role", "r", "--tool", "fs.read")
    assert result.exit_code == 3
    assert "team.yaml:42 rule 'r1': unknown operator 'lessthan'" in result.output


def test_check_reports_missing_file(invoke: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: str | Path) -> None:
        raise FileNotFoundError(f"no such file: {path}")

    monkeypatch.setattr(loader_mod, "load_policy", boom)
    result = invoke("check", "missing.yaml", "--role", "r", "--tool", "fs.read")
    assert result.exit_code == 3
    assert "no such file" in result.output


def test_check_reports_unimplemented_loader(invoke: Invoke, policy_file: Path) -> None:
    # The real loader may still be a stub; either way the CLI must not crash.
    result = invoke("check", str(policy_file), "--role", "r", "--tool", "fs.read")
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_check_reports_unimplemented_engine(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, fake_policy: list[Path], policy_file: Path
) -> None:
    from agent_castellan.policy import engine as engine_mod

    class Stub:
        def __init__(self, policy: object) -> None: ...

        def decide(self, *args: object) -> None:
            raise NotImplementedError

    monkeypatch.setattr(engine_mod, "PolicyEngine", Stub)
    result = invoke("check", str(policy_file), "--role", "r", "--tool", "fs.read")
    assert result.exit_code == 3
    assert "not implemented" in result.output


def test_check_reports_engine_error(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, fake_policy: list[Path], policy_file: Path
) -> None:
    from agent_castellan.policy import engine as engine_mod

    class Stub:
        def __init__(self, policy: object) -> None: ...

        def decide(self, *args: object) -> None:
            raise PolicyError("bad rule")

    monkeypatch.setattr(engine_mod, "PolicyEngine", Stub)
    result = invoke("check", str(policy_file), "--role", "r", "--tool", "fs.read")
    assert result.exit_code == 3
    assert "bad rule" in result.output


def test_explain_prints_trace_table_and_uses_check_exit_codes(
    invoke: Invoke, fake_policy: list[Path], policy_file: Path
) -> None:
    result = invoke("explain", str(policy_file), "--role", "coder", "--tool", "fs.write")
    assert result.exit_code == 2
    assert "ASK" in result.output
    assert "Rule trace" in result.output
    for rule in ("read-ok", "write-ask", "no-delete"):
        assert rule in result.output
    assert "yes" in result.output
    assert "no" in result.output


def test_explain_bad_args(invoke: Invoke, fake_policy: list[Path], policy_file: Path) -> None:
    result = invoke("explain", str(policy_file), "--role", "r", "--tool", "t", "--args", "nope")
    assert result.exit_code == 3
