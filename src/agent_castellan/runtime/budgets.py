"""Budget trackers: in-memory and SQLite (WS3).

Counters are keyed by run, `(run, role)`, `(run, agent)` and `(run, grant)`. Limits come from
the policy `budgets` section (run and per-role) and from `Grant.max_calls` (per grant).
`consume` checks and increments atomically and raises `BudgetExceeded` instead of going over.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import BudgetExceeded
from ..models import Decision, Effect, Grant, Principal, ToolCall
from ..policy.schema import BudgetsConfig
from ._common import immediate_transaction, init_sqlite

CALLS = "tool_calls"
COST = "cost_units"

CounterKey = tuple[str, str, str]  # (scope, name, metric) within one run


@dataclass(frozen=True)
class _Target:
    scope: str
    name: str
    label: str
    max_calls: float | None
    max_cost: float | None


def _targets(config: BudgetsConfig, principal: Principal, grants: Sequence[Grant]) -> list[_Target]:
    targets = [
        _Target("run", "", "run", config.run.max_tool_calls, config.run.max_cost_units),
        _Target("agent", principal.agent_id, f"agent '{principal.agent_id}'", None, None),
    ]
    role = config.per_role.get(principal.role)
    targets.append(
        _Target(
            "role",
            principal.role,
            f"role '{principal.role}'",
            role.max_tool_calls if role else None,
            role.max_cost_units if role else None,
        )
    )
    targets.extend(
        _Target("grant", g.grant_id, f"grant '{g.grant_id}'", g.max_calls, None) for g in grants
    )
    return targets


def _violation(
    targets: Sequence[_Target], get: Callable[[CounterKey], float], cost: float
) -> Decision | None:
    for t in targets:
        if t.max_calls is not None and get((t.scope, t.name, CALLS)) >= t.max_calls:
            return Decision(
                effect=Effect.DENY,
                reason=f"{t.label} budget exhausted: max_tool_calls={t.max_calls:g}",
                source="budget",
            )
        if t.max_cost is not None and get((t.scope, t.name, COST)) + cost > t.max_cost:
            return Decision(
                effect=Effect.DENY,
                reason=f"{t.label} budget exhausted: max_cost_units={t.max_cost:g}",
                source="budget",
            )
    return None


def _usage_name(scope: str, name: str, metric: str) -> str:
    return metric if scope == "run" else f"{scope}.{name}.{metric}"


class MemoryBudgetTracker:
    """Budget tracker held in process memory."""

    def __init__(self, config: BudgetsConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._counters: dict[str, dict[CounterKey, float]] = {}

    def precheck(
        self, principal: Principal, call: ToolCall, *, grants: Sequence[Grant] = ()
    ) -> Decision | None:
        """Return None when within budget, else a DENY decision with source budget."""
        targets = _targets(self._config, principal, grants)
        with self._lock:
            counters = self._counters.get(principal.run_id, {})
            return _violation(targets, lambda k: counters.get(k, 0.0), call.cost_units)

    def consume(
        self, principal: Principal, call: ToolCall, *, grants: Sequence[Grant] = ()
    ) -> None:
        """Record one allowed call against every applicable budget, or raise BudgetExceeded."""
        targets = _targets(self._config, principal, grants)
        with self._lock:
            counters = self._counters.setdefault(principal.run_id, {})
            blocked = _violation(targets, lambda k: counters.get(k, 0.0), call.cost_units)
            if blocked is not None:
                raise BudgetExceeded(blocked.reason)
            for t in targets:
                counters[(t.scope, t.name, CALLS)] = counters.get((t.scope, t.name, CALLS), 0) + 1
                counters[(t.scope, t.name, COST)] = (
                    counters.get((t.scope, t.name, COST), 0) + call.cost_units
                )

    def usage(self, run_id: str) -> dict[str, float]:
        """Return the counters recorded for a run."""
        with self._lock:
            counters = dict(self._counters.get(run_id, {}))
        result: dict[str, float] = {CALLS: 0.0, COST: 0.0}
        result.update({_usage_name(*k): v for k, v in counters.items()})
        return result


_BUDGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS budget_counters (
    run_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (run_id, scope, name, metric)
);
"""


class SqliteBudgetTracker(MemoryBudgetTracker):
    """Budget tracker persisted in SQLite; check-and-increment is atomic across processes."""

    def __init__(self, config: BudgetsConfig, path: str | Path) -> None:
        super().__init__(config)
        self._path = Path(path)
        init_sqlite(self._path, _BUDGET_SCHEMA)

    def _load(self, conn: sqlite3.Connection, run_id: str) -> dict[CounterKey, float]:
        rows = conn.execute(
            "SELECT scope, name, metric, value FROM budget_counters WHERE run_id = ?", (run_id,)
        ).fetchall()
        return {(s, n, m): v for s, n, m, v in rows}

    def precheck(
        self, principal: Principal, call: ToolCall, *, grants: Sequence[Grant] = ()
    ) -> Decision | None:
        """Return None when within budget, else a DENY decision with source budget."""
        targets = _targets(self._config, principal, grants)
        with immediate_transaction(self._path) as conn:
            counters = self._load(conn, principal.run_id)
        return _violation(targets, lambda k: counters.get(k, 0.0), call.cost_units)

    def consume(
        self, principal: Principal, call: ToolCall, *, grants: Sequence[Grant] = ()
    ) -> None:
        """Record one allowed call against every applicable budget, or raise BudgetExceeded."""
        targets = _targets(self._config, principal, grants)
        with immediate_transaction(self._path) as conn:
            counters = self._load(conn, principal.run_id)
            blocked = _violation(targets, lambda k: counters.get(k, 0.0), call.cost_units)
            if blocked is not None:
                raise BudgetExceeded(blocked.reason)
            for t in targets:
                for metric, delta in ((CALLS, 1.0), (COST, call.cost_units)):
                    conn.execute(
                        "INSERT INTO budget_counters VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT (run_id, scope, name, metric) "
                        "DO UPDATE SET value = value + excluded.value",
                        (principal.run_id, t.scope, t.name, metric, delta),
                    )

    def usage(self, run_id: str) -> dict[str, float]:
        """Return the counters recorded for a run."""
        with immediate_transaction(self._path) as conn:
            counters = self._load(conn, run_id)
        result: dict[str, float] = {CALLS: 0.0, COST: 0.0}
        result.update({_usage_name(*k): v for k, v in counters.items()})
        return result
