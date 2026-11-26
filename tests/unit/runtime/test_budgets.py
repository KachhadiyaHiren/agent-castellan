"""Budget tracker behaviour, run against both backends."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from agent_castellan.errors import BudgetExceeded
from agent_castellan.models import Effect, Grant, Principal, ToolCall
from agent_castellan.policy.schema import BudgetsConfig, RoleBudget, RunBudget
from agent_castellan.runtime.budgets import MemoryBudgetTracker, SqliteBudgetTracker
from agent_castellan.testing.fakes import EPOCH

Tracker = MemoryBudgetTracker
Factory = Callable[[BudgetsConfig], Tracker]


@pytest.fixture(params=["memory", "sqlite"])
def factory(request: pytest.FixtureRequest, tmp_path: Path) -> Factory:
    if request.param == "memory":
        return MemoryBudgetTracker
    return lambda config: SqliteBudgetTracker(config, tmp_path / "state.db")


def P(role: str = "coder", agent: str = "a1", run: str = "r1") -> Principal:  # noqa: N802
    return Principal(agent_id=agent, role=role, run_id=run)


CALL = ToolCall(tool="fs.read")


def _grant(grant_id: str, max_calls: int | None) -> Grant:
    return Grant(
        grant_id=grant_id,
        issuer_agent_id="a0",
        subject_agent_id="a1",
        subject_role="coder",
        run_id="r1",
        tools=("*",),
        expires_at=EPOCH + timedelta(hours=1),
        max_calls=max_calls,
        signature="x",
    )


def test_no_limits_means_always_within_budget(factory: Factory) -> None:
    t = factory(BudgetsConfig())
    for _ in range(5):
        assert t.precheck(P(), CALL) is None
        t.consume(P(), CALL)
    assert t.usage("r1")["tool_calls"] == 5


def test_run_call_limit_denies_after_exhaustion(factory: Factory) -> None:
    t = factory(BudgetsConfig(run=RunBudget(max_tool_calls=2)))
    for _ in range(2):
        t.consume(P(), CALL)
    decision = t.precheck(P(), CALL)
    assert decision is not None
    assert decision.effect is Effect.DENY
    assert decision.source == "budget"
    assert "run" in decision.reason


def test_run_budget_is_shared_across_the_agent_tree(factory: Factory) -> None:
    t = factory(BudgetsConfig(run=RunBudget(max_tool_calls=2)))
    t.consume(P("planner", "a0"), CALL)
    t.consume(P("coder", "a1"), CALL)
    assert t.precheck(P("researcher", "a2"), CALL) is not None


def test_runs_are_isolated(factory: Factory) -> None:
    t = factory(BudgetsConfig(run=RunBudget(max_tool_calls=1)))
    t.consume(P(run="r1"), CALL)
    assert t.precheck(P(run="r2"), CALL) is None
    assert t.usage("r2")["tool_calls"] == 0


def test_per_role_limit_only_affects_that_role(factory: Factory) -> None:
    t = factory(BudgetsConfig(per_role={"researcher": RoleBudget(max_tool_calls=1)}))
    t.consume(P("researcher", "a2"), CALL)
    blocked = t.precheck(P("researcher", "a3"), CALL)
    assert blocked is not None
    assert "researcher" in blocked.reason
    assert t.precheck(P("coder", "a1"), CALL) is None


def test_cost_units_are_limited(factory: Factory) -> None:
    t = factory(BudgetsConfig(run=RunBudget(max_cost_units=10)))
    t.consume(P(), ToolCall(tool="x", cost_units=6))
    assert t.precheck(P(), ToolCall(tool="x", cost_units=4)) is None
    blocked = t.precheck(P(), ToolCall(tool="x", cost_units=4.5))
    assert blocked is not None
    assert "max_cost_units" in blocked.reason
    assert t.usage("r1")["cost_units"] == 6


def test_role_cost_limit(factory: Factory) -> None:
    t = factory(BudgetsConfig(per_role={"coder": RoleBudget(max_cost_units=1)}))
    assert t.precheck(P(), ToolCall(tool="x", cost_units=2)) is not None


def test_grant_max_calls_is_counted_per_grant(factory: Factory) -> None:
    t = factory(BudgetsConfig())
    g1, g2 = _grant("g1", 1), _grant("g2", None)
    t.consume(P(), CALL, grants=[g1, g2])
    blocked = t.precheck(P(), CALL, grants=[g1, g2])
    assert blocked is not None
    assert "g1" in blocked.reason
    assert t.precheck(P(), CALL, grants=[g2]) is None
    assert t.usage("r1")["grant.g2.tool_calls"] == 1


def test_consume_over_limit_raises_and_does_not_count(factory: Factory) -> None:
    t = factory(BudgetsConfig(run=RunBudget(max_tool_calls=1)))
    t.consume(P(), CALL)
    with pytest.raises(BudgetExceeded):
        t.consume(P(), CALL)
    assert t.usage("r1")["tool_calls"] == 1


def test_usage_reports_every_counter_scope(factory: Factory) -> None:
    t = factory(BudgetsConfig())
    t.consume(P("coder", "a1"), ToolCall(tool="x", cost_units=2))
    usage = t.usage("r1")
    assert usage["tool_calls"] == 1
    assert usage["cost_units"] == 2
    assert usage["role.coder.tool_calls"] == 1
    assert usage["agent.a1.tool_calls"] == 1
    assert usage["agent.a1.cost_units"] == 2


def test_unknown_run_usage_is_zero(factory: Factory) -> None:
    assert factory(BudgetsConfig()).usage("none") == {"tool_calls": 0.0, "cost_units": 0.0}


def test_threads_never_exceed_limits(factory: Factory) -> None:
    limit = 25
    t = factory(
        BudgetsConfig(
            run=RunBudget(max_tool_calls=limit), per_role={"coder": RoleBudget(max_tool_calls=20)}
        )
    )
    ok: list[int] = []
    barrier = threading.Barrier(8)

    def worker(n: int) -> None:
        barrier.wait()
        for _ in range(10):
            try:
                t.consume(P("coder" if n % 2 == 0 else "other", f"a{n}"), CALL)
                ok.append(n)
            except BudgetExceeded:
                pass

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    usage = t.usage("r1")
    assert usage["tool_calls"] == len(ok) == limit
    assert usage.get("role.coder.tool_calls", 0.0) <= 20


def test_sqlite_is_correct_across_two_connections(tmp_path: Path) -> None:
    config = BudgetsConfig(run=RunBudget(max_tool_calls=10))
    a = SqliteBudgetTracker(config, tmp_path / "s.db")
    b = SqliteBudgetTracker(config, tmp_path / "s.db")
    wins: list[int] = []

    def worker(tracker: SqliteBudgetTracker) -> None:
        for _ in range(10):
            try:
                tracker.consume(P(), CALL)
                wins.append(1)
            except BudgetExceeded:
                pass

    threads = [threading.Thread(target=worker, args=(x,)) for x in (a, b, a, b)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(wins) == 10
    assert a.usage("r1")["tool_calls"] == b.usage("r1")["tool_calls"] == 10
    assert a.precheck(P(), CALL) is not None
    assert b.precheck(P(), CALL) is not None
