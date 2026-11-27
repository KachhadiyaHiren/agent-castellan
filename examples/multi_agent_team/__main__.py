"""Command line: ``python -m examples.multi_agent_team --scripted``."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .models import ChatModel, OpenAICompatibleModel
from .scenarios import SCENARIOS, get_scenario, run_scenario, run_team
from .timeline import build_table

DEFAULT_LIVE_TASK = (
    "Research how a token bucket rate limiter works, then add a rate limiter to the demo "
    "project as /workspace/limiter.py. Delegate the research and the coding."
)


def main(argv: list[str] | None = None) -> int:
    """Run the scripted scenarios, or a task against a real OpenAI-compatible endpoint."""
    parser = argparse.ArgumentParser(
        prog="python -m examples.multi_agent_team", description=__doc__
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--scripted", action="store_true", help="deterministic scripted run (default)"
    )
    mode.add_argument("--live", action="store_true", help="use an OpenAI-compatible endpoint")
    parser.add_argument(
        "--scenario",
        default="all",
        help=f"scenario name or 'all' (default). Names: {', '.join(s.name for s in SCENARIOS)}",
    )
    parser.add_argument("--task", default=DEFAULT_LIVE_TASK, help="task for --live runs")
    parser.add_argument("--workdir", type=Path, help="keep the audit log and policy copy here")
    args = parser.parse_args(argv)

    console = Console()
    if args.live:
        return _live(console, args.task, args.workdir)
    names = [s.name for s in SCENARIOS] if args.scenario == "all" else [args.scenario]
    try:
        for name in names:
            scenario = get_scenario(name)
            result = run_scenario(name, args.workdir)
            console.rule(f"[bold]{scenario.title}")
            console.print(f"[dim]task:[/] {scenario.task}")
            console.print(build_table(result.events))
            console.print(f"[dim]planner answer:[/] {result.answer}\n")
    except KeyError as exc:
        console.print(f"[red]{exc.args[0]}[/]")
        return 2
    if args.workdir:
        console.print(f"Audit log: {args.workdir / 'castellan-audit.jsonl'}")
    return 0


def _live(console: Console, task: str, workdir: Path | None) -> int:
    try:
        OpenAICompatibleModel.from_env()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 2

    def factory(_role: str) -> ChatModel:
        return OpenAICompatibleModel.from_env()

    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        result = run_team(task, factory, workdir)
    else:
        with tempfile.TemporaryDirectory(prefix="castellan-run-") as tmp:
            result = run_team(task, factory, Path(tmp))
    console.print(build_table(result.events, title="Live run"))
    console.print(Panel(result.answer, title="planner answer"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
