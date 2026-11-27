"""One test per scenario of the multi-agent reference team.

The scenarios are deterministic, so ``test_readme_shows_real_output`` also proves that
the timelines printed in ``examples/multi_agent_team/README.md`` are what the code
really produces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from examples.multi_agent_team import (
    SCENARIOS,
    OpenAICompatibleModel,
    ScenarioResult,
    ScriptedModel,
    run_scenario,
)
from examples.multi_agent_team.__main__ import main
from examples.multi_agent_team.models import (
    CallAction,
    DelegateAction,
    FinalAction,
    Message,
    call,
    delegate,
    final,
    parse_action,
)
from examples.multi_agent_team.timeline import render_text

from agent_castellan.audit.verify import verify_log

README = Path(__file__).parents[2] / "examples" / "multi_agent_team" / "README.md"


def rows(result: ScenarioResult) -> list[tuple[str, str, str]]:
    """Return (agent, action prefix, outcome) for every event."""
    return [(e.agent, e.action.split(" ")[0], e.outcome) for e in result.events]


def test_happy_path_allows_every_step() -> None:
    result = run_scenario("happy-path")
    assert [e.outcome for e in result.events] == ["ALLOW"] * 6
    assert {e.cause for e in result.events if e.agent != "planner"} == {
        "rule research-web",
        "rule read-workspace",
    }
    assert result.answer == "Research and project review done."


def test_secret_read_is_denied_by_rule_and_agent_adapts() -> None:
    result = run_scenario("secret-denied")
    denied = [e for e in result.events if e.outcome == "DENY"]
    assert [e.cause for e in denied] == ["rule no-secrets"]
    assert rows(result)[-1] == ("coder", "fs.read", "ALLOW")  # it read the README instead


def test_researcher_cannot_delegate_past_depth_limit() -> None:
    result = run_scenario("depth-blocked")
    last = result.events[-1]
    assert (last.agent, last.outcome) == ("researcher", "DENY")
    assert "may not delegate to 'coder' at depth 1" in last.cause


def test_runaway_researcher_is_stopped_by_role_budget() -> None:
    result = run_scenario("budget-runaway")
    searches = [e for e in result.events if e.agent == "researcher"]
    assert [e.outcome for e in searches] == ["ALLOW"] * 3 + ["DENY"] * 2
    assert "budget exhausted: max_tool_calls=3" in searches[-1].cause


def test_coder_write_is_approved_by_reviewer_then_retry_succeeds(tmp_path: Path) -> None:
    result = run_scenario("approval-flow", tmp_path)
    outcomes = [e.outcome for e in result.events if e.action.startswith(("fs.write", "resolve"))]
    assert outcomes == ["ASK", "APPROVED", "ALLOW"]
    assert result.events[-1].cause == "approval of rule write-needs-review"
    assert verify_log(result.audit_path).ok


def test_forged_grant_is_rejected() -> None:
    result = run_scenario("tampered-grant")
    honest, forged = result.events[-2:]
    assert "not covered by grant 0" in honest.cause
    assert forged.outcome == "DENY"
    assert "signature of grant 0 is invalid" in forged.cause


def test_readme_shows_real_output() -> None:
    readme = README.read_text()
    for scenario in SCENARIOS:
        text = render_text(run_scenario(scenario.name).events)
        assert text in readme, f"README timeline for {scenario.name} is out of date"


def test_cli_scripted_runs_every_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--scripted"]) == 0
    out = capsys.readouterr().out
    assert all(s.title in out for s in SCENARIOS)
    assert main(["--scenario", "nope"]) == 2


def test_cli_live_needs_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CASTELLAN_EXAMPLE_BASE_URL", raising=False)
    assert main(["--live"]) == 2
    assert "CASTELLAN_EXAMPLE_BASE_URL" in capsys.readouterr().out


def test_parse_action_handles_all_shapes() -> None:
    assert parse_action(call("fs.read", path="/workspace/a")) == CallAction(
        "fs.read", {"path": "/workspace/a"}
    )
    assert parse_action(delegate("coder", ["fs.read"], "t")) == DelegateAction(
        "coder", ("fs.read",), "t"
    )
    assert parse_action(final("done")) == FinalAction("done")
    assert parse_action('Sure!\n```json\n{"action":"final","text":"x"}\n```') == FinalAction("x")
    assert parse_action("just words") == FinalAction("just words")
    assert parse_action("{broken") == FinalAction("{broken")


def test_scripted_model_replays_then_finishes() -> None:
    model = ScriptedModel([call("fs.list", path="/workspace")])
    assert parse_action(model.complete([])) == CallAction("fs.list", {"path": "/workspace"})
    assert parse_action(model.complete([])) == FinalAction("(script finished)")


def test_openai_compatible_model_posts_chat_completion() -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, headers: dict[str, str], body: dict[str, object]) -> dict[str, object]:
        seen.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": '```json\n{"action":"final"}\n```'}}]}

    model = OpenAICompatibleModel("http://llm.test/v1/", "m", "k", post=fake_post)
    assert model.complete([Message("user", "hi")]) == '{"action":"final"}'
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k"  # type: ignore[index]
    with pytest.raises(RuntimeError, match="unexpected reply"):
        OpenAICompatibleModel("http://x", "m", post=lambda *_: {}).complete([])


def test_from_env_reads_documented_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASTELLAN_EXAMPLE_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("CASTELLAN_EXAMPLE_MODEL", "m")
    assert isinstance(OpenAICompatibleModel.from_env(), OpenAICompatibleModel)
