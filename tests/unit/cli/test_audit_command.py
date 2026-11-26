"""`castellan audit verify` and `castellan audit tail`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_castellan.audit import verify as verify_mod
from agent_castellan.errors import CastellanError
from agent_castellan.models import Decision, Effect, Principal, ToolCall
from agent_castellan.testing.fakes import FakeAuditSink, FrozenClock

Invoke = Callable[..., Any]


def make_log(tmp_path: Path) -> Path:
    sink = FakeAuditSink(FrozenClock())
    lines = []
    for i, (run, tool, effect) in enumerate(
        [("run-a", "fs.read", Effect.ALLOW), ("run-b", "fs.write", Effect.ASK)] * 3
    ):
        principal = Principal(agent_id=f"ag{i}", role="coder", run_id=run)
        decision = Decision(effect=effect, reason="r", rule_id="rule-1" if i % 2 == 0 else None)
        lines.append(sink.append(principal, ToolCall(tool=tool), decision).model_dump_json())
    path = tmp_path / "audit.jsonl"
    path.write_text("\n".join(lines) + "\n\n")
    return path


def test_verify_ok(invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Path] = []

    def fake(path: str | Path) -> verify_mod.VerifyResult:
        seen.append(Path(path))
        return verify_mod.VerifyResult(ok=True, entries=6)

    monkeypatch.setattr(verify_mod, "verify_log", fake)
    result = invoke("audit", "verify", str(tmp_path / "a.jsonl"))
    assert result.exit_code == 0
    assert "OK: 6 entries" in result.output
    assert seen == [tmp_path / "a.jsonl"]


def test_verify_tampered(invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        verify_mod,
        "verify_log",
        lambda path: verify_mod.VerifyResult(False, 6, bad_seq=3, reason="hash_mismatch"),
    )
    result = invoke("audit", "verify", str(tmp_path / "a.jsonl"))
    assert result.exit_code == 1
    assert "FAILED at seq 3: hash_mismatch" in result.output


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (NotImplementedError(), "not implemented"),
        (FileNotFoundError("no such log"), "no such log"),
        (CastellanError("unreadable"), "unreadable"),
    ],
)
def test_verify_errors(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception, text: str
) -> None:
    def boom(path: str | Path) -> None:
        raise exc

    monkeypatch.setattr(verify_mod, "verify_log", boom)
    result = invoke("audit", "verify", str(tmp_path / "a.jsonl"))
    assert result.exit_code == 3
    assert text in result.output


def test_tail_default_shows_all_in_order(invoke: Invoke, tmp_path: Path) -> None:
    result = invoke("audit", "tail", str(make_log(tmp_path)))
    assert result.exit_code == 0
    rows = result.output.splitlines()
    assert len(rows) == 6
    assert rows[0].startswith("0 ")
    assert "tool=fs.read effect=allow rule=rule-1" in rows[0]
    assert "tool=fs.write effect=ask rule=-" in rows[1]


def test_tail_filters_by_run(invoke: Invoke, tmp_path: Path) -> None:
    result = invoke("audit", "tail", str(make_log(tmp_path)), "--run", "run-b")
    rows = result.output.splitlines()
    assert len(rows) == 3
    assert all("run=run-b" in r for r in rows)


def test_tail_limits_lines(invoke: Invoke, tmp_path: Path) -> None:
    result = invoke("audit", "tail", str(make_log(tmp_path)), "-n", "2")
    rows = result.output.splitlines()
    assert [r.split()[0] for r in rows] == ["4", "5"]


def test_tail_missing_file(invoke: Invoke, tmp_path: Path) -> None:
    result = invoke("audit", "tail", str(tmp_path / "nope.jsonl"))
    assert result.exit_code == 3


def test_tail_rejects_garbage_line(invoke: Invoke, tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n")
    result = invoke("audit", "tail", str(path))
    assert result.exit_code == 3
    assert f"{path}:1" in result.output
