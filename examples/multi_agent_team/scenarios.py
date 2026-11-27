"""The six scripted scenarios. Each one builds a fresh run, so budgets never leak between them."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_castellan import Guard

from .agents import Team
from .models import ChatModel, ScriptedModel, call, delegate, final
from .timeline import Event
from .tools import Workspace, build_tools

POLICY_PATH = Path(__file__).parent / "policy.yaml"
# A fixed demo key keeps grants verifiable and avoids the "random key" warning.
DEMO_KEY = b"castellan-example-key-0123456789"
FETCH_URL = "https://example.test/token-bucket"


@dataclass(frozen=True)
class ScenarioResult:
    """What a scenario produced: the timeline, the planner's answer and the audit log path."""

    name: str
    events: tuple[Event, ...]
    answer: str
    audit_path: Path


@dataclass(frozen=True)
class Scenario:
    """A named scenario: a task, per-role scripts and optional extra steps after the run."""

    name: str
    title: str
    task: str
    scripts: Mapping[str, Sequence[str]]
    after: Callable[[Team], None] | None = None


def make_guard(workdir: Path) -> Guard:
    """Load the example policy, pointing its audit log inside ``workdir``."""
    audit = workdir / "castellan-audit.jsonl"
    text = POLICY_PATH.read_text()
    marker = "path: ./castellan-audit.jsonl"
    if marker not in text:
        raise RuntimeError("policy.yaml no longer contains the audit path placeholder")
    policy = workdir / "policy.yaml"
    policy.write_text(text.replace(marker, f"path: {audit}"))
    return Guard.from_file(policy, key=DEMO_KEY)


def _forge(team: Team) -> None:
    """The coder widens its own grant and presents it: the signature no longer matches."""
    coder = team.agents["coder"]
    forged = team.grants["coder"].model_copy(update={"tools": ("fs.*",)})
    team.act(
        coder,
        "fs.write",
        {"path": "/workspace/limiter.py", "content": "print('hi')"},
        chain=(forged,),
        note=" [forged grant]",
    )


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "happy-path",
        "Happy path: delegation, research, read",
        "Look at the demo project and research how to add a rate limiter.",
        {
            "planner": [
                delegate("researcher", ["web.search", "web.fetch"], "Research token buckets."),
                delegate("coder", ["fs.list", "fs.read"], "Inspect the project."),
                final("Research and project review done."),
            ],
            "researcher": [
                call("web.search", query="token bucket rate limiter"),
                call("web.fetch", url=FETCH_URL),
                final("Token bucket: refill at a fixed rate, take one token per request."),
            ],
            "coder": [
                call("fs.list", path="/workspace"),
                call("fs.read", path="/workspace/README.md"),
                final("The project is a tiny service that needs a rate limiter."),
            ],
        },
    ),
    Scenario(
        "secret-denied",
        "Coder tries to read .env, is denied, and adapts",
        "Check how the demo project is configured.",
        {
            "planner": [
                delegate("coder", ["fs.list", "fs.read"], "Find the configuration."),
                final("Done."),
            ],
            "coder": [
                call("fs.read", path="/workspace/.env"),
                call("fs.read", path="/workspace/README.md"),
                final("I could not read .env; the README says the project has no config yet."),
            ],
        },
    ),
    Scenario(
        "depth-blocked",
        "Researcher tries to delegate further and is blocked by depth",
        "Research rate limiting, then have the code written.",
        {
            "planner": [
                delegate("researcher", ["web.search", "web.fetch"], "Research rate limiting."),
                final("Done."),
            ],
            "researcher": [
                call("web.search", query="sliding window rate limiter"),
                delegate("coder", ["fs.write"], "Write the limiter for me."),
                final("Search finished; I could not hand the coding off."),
            ],
        },
    ),
    Scenario(
        "budget-runaway",
        "Runaway researcher hits its per-role budget",
        "Research rate limiting.",
        {
            "planner": [
                delegate("researcher", ["web.search", "web.fetch"], "Research rate limiting."),
                final("Done."),
            ],
            "researcher": [
                *(
                    call("web.search", query=q)
                    for q in (
                        "rate limiter",
                        "rate limiter python",
                        "token bucket",
                        "sliding window",
                        "leaky bucket",
                    )
                ),
                final("Stopped searching: the budget ran out."),
            ],
        },
    ),
    Scenario(
        "approval-flow",
        "Coder write needs the reviewer's approval, then succeeds on retry",
        "Write a rate limiter into the demo project.",
        {
            "planner": [
                delegate("coder", ["fs.list", "fs.read", "fs.write"], "Write limiter.py."),
                final("limiter.py written after review."),
            ],
            "coder": [
                call("fs.read", path="/workspace/README.md"),
                call(
                    "fs.write",
                    path="/workspace/limiter.py",
                    content="class Bucket: ...",
                ),
                final("limiter.py is in place."),
            ],
            "reviewer": [
                call("fs.read", path="/workspace/README.md"),
                final("APPROVE: the file matches the README request and touches nothing else."),
            ],
        },
    ),
    Scenario(
        "tampered-grant",
        "Coder forges a wider grant and is rejected",
        "Write a rate limiter into the demo project.",
        {
            "planner": [
                delegate("coder", ["fs.list", "fs.read"], "Inspect the project only."),
                final("Done."),
            ],
            "coder": [
                call("fs.write", path="/workspace/limiter.py", content="print('hi')"),
                final("I could not write; trying another way."),
            ],
        },
        after=_forge,
    ),
)


def get_scenario(name: str) -> Scenario:
    """Look a scenario up by name.

    Raises:
        KeyError: if no scenario has that name.
    """
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"unknown scenario {name!r}; choose from {[s.name for s in SCENARIOS]}")


def run_team(
    task: str,
    model_factory: Callable[[str], ChatModel],
    workdir: Path,
    after: Callable[[Team], None] | None = None,
) -> ScenarioResult:
    """Run one task with the given models in ``workdir`` and return the result."""
    workspace = Workspace()
    try:
        team = Team(make_guard(workdir), build_tools(workspace), model_factory)
        answer = team.run(task)
        if after is not None:
            after(team)
    finally:
        workspace.close()
    return ScenarioResult("run", tuple(team.timeline), answer, workdir / "castellan-audit.jsonl")


def run_scenario(name: str, workdir: Path | None = None) -> ScenarioResult:
    """Run a scripted scenario by name (in a fresh temp directory unless one is given)."""
    scenario = get_scenario(name)

    def factory(role: str) -> ChatModel:
        return ScriptedModel(scenario.scripts.get(role, []))

    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        result = run_team(scenario.task, factory, workdir, scenario.after)
    else:
        with tempfile.TemporaryDirectory(prefix="castellan-run-") as tmp:
            result = run_team(scenario.task, factory, Path(tmp), scenario.after)
    return ScenarioResult(name, result.events, result.answer, result.audit_path)
