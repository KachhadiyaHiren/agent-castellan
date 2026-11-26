"""Shared builders: a Guard wired entirely from the in-memory fakes."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_castellan.guard import Guard
from agent_castellan.models import Effect, Principal
from agent_castellan.testing.fakes import (
    FakeApprovalStore,
    FakeAuditSink,
    FakeBudgetTracker,
    FakeDecider,
    FakeGrantVerifier,
    FrozenClock,
)


@dataclass
class Rig:
    guard: Guard
    decider: FakeDecider
    audit: FakeAuditSink
    approvals: FakeApprovalStore
    principal: Principal


def make_rig(effects: dict[str, Effect], *, default: Effect = Effect.DENY) -> Rig:
    clock = FrozenClock()
    decider = FakeDecider(effects, default=default)
    audit = FakeAuditSink(clock)
    approvals = FakeApprovalStore(clock)
    guard = Guard(decider, FakeGrantVerifier(clock), approvals, FakeBudgetTracker(), audit, clock)
    return Rig(guard, decider, audit, approvals, guard.start_run("coder"))


@pytest.fixture
def rig() -> Rig:
    return make_rig({"fs.read": Effect.ALLOW, "fs.write": Effect.ASK})
