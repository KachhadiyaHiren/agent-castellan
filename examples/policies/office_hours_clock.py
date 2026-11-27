"""Test the office-hours window of office-hours.yaml with a pinned clock.

`castellan test` uses the real clock, so time-of-day rules are tested from Python instead.
Run from the repository root: `uv run python examples/policies/office_hours_clock.py`.
"""

from datetime import UTC, datetime

from agent_castellan import Principal, ToolCall
from agent_castellan.policy.engine import PolicyEngine
from agent_castellan.policy.loader import load_policy

policy = load_policy("examples/policies/office-hours.yaml")
agent = Principal(agent_id="a1", role="ops_agent", run_id="r1")
call = ToolCall(tool="ops.restart_service", args={"name": "api"})


class FixedClock:
    def __init__(self, when: datetime) -> None:
        self.when = when

    def now(self) -> datetime:
        return self.when


for label, when in [
    ("Wednesday 10:00 UTC", datetime(2026, 12, 2, 10, 0, tzinfo=UTC)),
    ("Wednesday 17:00 UTC", datetime(2026, 12, 2, 17, 0, tzinfo=UTC)),
    ("Saturday 10:00 UTC", datetime(2026, 12, 5, 10, 0, tzinfo=UTC)),
]:
    decision = PolicyEngine(policy, clock=FixedClock(when)).decide(agent, call)
    print(f"{label}: {decision.effect.value}")
