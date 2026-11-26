"""Shared fakes for CLI tests: the other workstreams' functions are replaced by small fakes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from agent_castellan.models import Decision, Effect, Principal, ToolCall, TraceStep
from agent_castellan.policy import engine as engine_mod
from agent_castellan.policy import loader as loader_mod
from agent_castellan.policy.schema import Policy
from agent_castellan.testing.fakes import FakeDecider


class FakeEngine(FakeDecider):
    """Decides by tool name using `RULES`; adds a trace and fake rule ids."""

    RULES: ClassVar[dict[str, tuple[Effect, str]]] = {
        "fs.read": (Effect.ALLOW, "read-ok"),
        "fs.write": (Effect.ASK, "write-ask"),
        "fs.delete": (Effect.DENY, "no-delete"),
    }

    def __init__(self, policy: Policy) -> None:
        super().__init__()
        self.policy = policy

    def decide(self, principal: Principal, call: ToolCall) -> Decision:
        """Return the canned decision, recording what the engine was asked."""
        effect, rule_id = self.RULES.get(call.tool, (Effect.DENY, ""))
        trace = tuple(
            TraceStep(rule_id=rid, matched=rid == rule_id, detail=f"tool {call.tool}")
            for _, rid in self.RULES.values()
        )
        if not rule_id:
            return Decision(effect=effect, reason="default deny", source="default", trace=trace)
        return Decision(effect=effect, reason="fake", rule_id=rule_id, trace=trace)


@pytest.fixture
def runner() -> CliRunner:
    """CLI runner with stdout and stderr separated."""
    return CliRunner()


@pytest.fixture
def fake_policy(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace the loader and engine with fakes; returns the list of loaded paths."""
    loaded: list[Path] = []

    def load_policy(path: str | Path) -> Policy:
        loaded.append(Path(path))
        return Policy(source=str(path))

    monkeypatch.setattr(loader_mod, "load_policy", load_policy)
    monkeypatch.setattr(engine_mod, "PolicyEngine", FakeEngine)
    return loaded


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    """A placeholder policy path (contents are irrelevant to the fakes)."""
    path = tmp_path / "team.yaml"
    path.write_text("version: 1\n")
    return path


@pytest.fixture
def invoke(runner: CliRunner) -> Callable[..., object]:
    """Invoke the real app (imported late so registration sees the patches)."""
    from agent_castellan.cli.app import app

    def _invoke(*args: str) -> object:
        return runner.invoke(app, list(args))

    return _invoke
