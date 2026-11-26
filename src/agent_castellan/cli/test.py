"""`castellan test` command: run policy test files (PLAN section 3.4)."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ..errors import CastellanError
from ..models import Effect, Principal, ToolCall
from ..policy import engine, loader


class AgentSpec(BaseModel):
    """The agent a test case runs as."""

    model_config = ConfigDict(extra="forbid")
    role: str
    depth: int = 0
    agent_id: str = "test-agent"
    run_id: str = "test-run"
    parent_role: str | None = None
    on_behalf_of: str | None = None


class CallSpec(BaseModel):
    """The tool call a test case makes."""

    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)


class CaseSpec(BaseModel):
    """One expectation about a decision."""

    model_config = ConfigDict(extra="forbid")
    name: str
    agent: AgentSpec
    call: CallSpec
    expect: Effect
    expect_rule: str | None = None


class TestFileSpec(BaseModel):
    """A whole policy test file."""

    __test__ = False
    model_config = ConfigDict(extra="forbid")
    policy: str
    cases: list[CaseSpec]


@dataclass
class CaseResult:
    """Outcome of one case; `message` is set on failure."""

    name: str
    message: str | None = None

    @property
    def passed(self) -> bool:
        """True when the case met every expectation."""
        return self.message is None


@dataclass
class FileResult:
    """Outcome of one test file; `error` is set when the file could not be run at all."""

    path: Path
    cases: list[CaseResult] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


def _run_case(decider: engine.PolicyEngine, case: CaseSpec) -> CaseResult:
    principal = Principal(
        agent_id=case.agent.agent_id,
        role=case.agent.role,
        run_id=case.agent.run_id,
        parent_role=case.agent.parent_role,
        depth=case.agent.depth,
        on_behalf_of=case.agent.on_behalf_of,
    )
    call = ToolCall(tool=case.call.tool, args=case.call.args, resource=case.call.resource)
    decision = decider.decide(principal, call)
    got_rule = decision.rule_id or "none"
    if decision.effect is not case.expect:
        return CaseResult(
            case.name,
            f"expected {case.expect.value}, got {decision.effect.value} "
            f"(rule: {got_rule}, reason: {decision.reason})",
        )
    if case.expect_rule is not None and decision.rule_id != case.expect_rule:
        return CaseResult(case.name, f"expected rule {case.expect_rule}, got {got_rule}")
    return CaseResult(case.name)


def run_test_file(path: Path) -> FileResult:
    """Run every case in one policy test file."""
    result = FileResult(path)
    start = time.perf_counter()
    try:
        raw = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        spec = TestFileSpec.model_validate(raw)
        policy = loader.load_policy(path.parent / spec.policy)
        decider = engine.PolicyEngine(policy)
        result.cases = [_run_case(decider, case) for case in spec.cases]
    except (OSError, YAMLError, ValidationError, CastellanError) as exc:
        result.error = str(exc)
    except NotImplementedError:
        result.error = "the policy loader or engine is not implemented yet"
    result.seconds = time.perf_counter() - start
    return result


def _write_junit(results: list[FileResult], destination: Path, seconds: float) -> None:
    total = sum(max(len(r.cases), 1) for r in results)
    failures = sum(1 for r in results for c in r.cases if not c.passed)
    errors = sum(1 for r in results if r.error)
    suite = ET.Element(
        "testsuite",
        name="castellan",
        tests=str(total),
        failures=str(failures),
        errors=str(errors),
        time=f"{seconds:.3f}",
    )
    for r in results:
        if r.error:
            case = ET.SubElement(suite, "testcase", classname=str(r.path), name="load")
            ET.SubElement(case, "error", message=r.error).text = r.error
            continue
        for c in r.cases:
            case = ET.SubElement(suite, "testcase", classname=str(r.path), name=c.name)
            if c.message is not None:
                ET.SubElement(case, "failure", message=c.message).text = c.message
    tree = ET.ElementTree(suite)
    ET.indent(tree)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def run_tests(
    files: Annotated[list[Path], typer.Argument(help="Policy test YAML files.")],
    junit: Annotated[Path | None, typer.Option("--junit", help="Write a JUnit XML report.")] = None,
) -> None:
    """Run policy test files. Exit 1 if any case fails or any file cannot be run."""
    started = time.perf_counter()
    results = [run_test_file(path) for path in files]
    for r in results:
        marks = "E" if r.error else "".join("." if c.passed else "F" for c in r.cases)
        typer.echo(f"{r.path} {marks}")

    problems = [r for r in results if r.error or any(not c.passed for c in r.cases)]
    if problems:
        typer.echo("\n=== FAILURES ===")
    for r in problems:
        if r.error:
            typer.echo(f"ERROR {r.path}: {r.error}")
        for c in r.cases:
            if not c.passed:
                typer.echo(f"FAILED {r.path}::{c.name}\n    {c.message}")

    cases = [c for r in results for c in r.cases]
    failed = sum(1 for c in cases if not c.passed)
    errored = sum(1 for r in results if r.error)
    elapsed = time.perf_counter() - started
    parts = [f"{len(cases) - failed} passed"]
    if failed:
        parts.append(f"{failed} failed")
    if errored:
        parts.append(f"{errored} error{'s' if errored != 1 else ''}")
    typer.echo(f"\n=== {', '.join(parts)} in {elapsed:.2f}s ===")

    if junit is not None:
        _write_junit(results, junit, elapsed)
    raise typer.Exit(1 if failed or errored else 0)


def register(app: typer.Typer) -> None:
    """Register the `test` command on the CLI app."""
    app.command("test", help="Run policy test files.")(run_tests)
