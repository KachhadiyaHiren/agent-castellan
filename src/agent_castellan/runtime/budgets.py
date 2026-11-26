"""Budget trackers: in-memory and SQLite (WS3)."""

from __future__ import annotations

from pathlib import Path

from ..models import Decision, Principal, ToolCall
from ..policy.schema import BudgetsConfig


class MemoryBudgetTracker:
    """Budget tracker held in process memory."""

    def __init__(self, config: BudgetsConfig) -> None:
        self._config = config

    def precheck(self, principal: Principal, call: ToolCall) -> Decision | None:
        """Return None when within budget, else a DENY decision with source budget."""
        raise NotImplementedError

    def consume(self, principal: Principal, call: ToolCall) -> None:
        """Record one allowed call against every applicable budget."""
        raise NotImplementedError

    def usage(self, run_id: str) -> dict[str, float]:
        """Return the counters recorded for a run."""
        raise NotImplementedError


class SqliteBudgetTracker(MemoryBudgetTracker):
    """Budget tracker persisted in SQLite."""

    def __init__(self, config: BudgetsConfig, path: str | Path) -> None:
        super().__init__(config)
        self._path = Path(path)
