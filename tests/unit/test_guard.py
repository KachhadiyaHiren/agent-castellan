"""Full pipeline tests for Guard using only fakes."""

from __future__ import annotations

import pytest

from agent_castellan import Effect, Guard, PermissionDenied, Principal, ToolCall
from agent_castellan.models import ApprovalStatus
from agent_castellan.testing.fakes import (
    FakeApprovalStore,
    FakeAuditSink,
    FakeBudgetTracker,
    FakeDecider,
    FakeGrantVerifier,
    FrozenClock,
)


class Rig:
    """A Guard wired to fakes, with the fakes exposed for assertions."""

    def __init__(
        self,
        effects: dict[str, Effect] | None = None,
        *,
        default: Effect = Effect.DENY,
        max_calls: int | None = None,
        grant_denies: tuple[str, ...] = (),
    ) -> None:
        self.clock = FrozenClock()
        self.decider = FakeDecider(
            effects, default=default, delegations={"planner": ["coder"], "coder": ["coder"]}
        )
        self.grants = FakeGrantVerifier(self.clock, deny_tools=grant_denies)
        self.approvals = FakeApprovalStore(self.clock)
        self.budgets = FakeBudgetTracker(max_calls)
        self.audit = FakeAuditSink(self.clock)
        self.guard = Guard(
            self.decider, self.grants, self.approvals, self.budgets, self.audit, self.clock
        )


def call(tool: str, **args: object) -> ToolCall:
    return ToolCall(tool=tool, args=dict(args))


def root(rig: Rig, role: str = "planner") -> Principal:
    return rig.guard.start_run(role, on_behalf_of="user-1")


def test_allow_rule_returns_allow_and_consumes_budget() -> None:
    rig = Rig({"fs.read": Effect.ALLOW})
    decision = rig.guard.authorize(root(rig), call("fs.read", path="/a"))
    assert decision.effect is Effect.ALLOW
    assert len(rig.budgets.consumed) == 1


def test_deny_rule_returns_deny_and_does_not_consume_budget() -> None:
    rig = Rig({"fs.delete": Effect.DENY})
    decision = rig.guard.authorize(root(rig), call("fs.delete"))
    assert decision.effect is Effect.DENY
    assert rig.budgets.consumed == []


def test_unlisted_tool_falls_back_to_default_effect() -> None:
    rig = Rig()
    assert rig.guard.authorize(root(rig), call("nope")).effect is Effect.DENY


def test_ask_creates_pending_request_with_approval_id() -> None:
    rig = Rig({"fs.write": Effect.ASK})
    decision = rig.guard.authorize(root(rig), call("fs.write", path="/a"))
    assert decision.effect is Effect.ASK
    assert decision.approval_id is not None
    assert len(rig.approvals.pending()) == 1
    assert rig.budgets.consumed == []


def test_ask_then_approve_then_retry_allows_once() -> None:
    rig = Rig({"fs.write": Effect.ASK})
    agent = root(rig)
    first = rig.guard.authorize(agent, call("fs.write", path="/a"))
    assert first.approval_id is not None
    status = rig.guard.approve(first.approval_id, approver_id="reviewer-1")
    assert status is ApprovalStatus.APPROVED

    retry = rig.guard.authorize(agent, call("fs.write", path="/a"))
    assert retry.effect is Effect.ALLOW
    assert retry.source == "approval"
    assert len(rig.budgets.consumed) == 1

    again = rig.guard.authorize(agent, call("fs.write", path="/a"))
    assert again.effect is Effect.ASK  # approval is single-use


def test_approval_does_not_cover_different_arguments() -> None:
    rig = Rig({"fs.write": Effect.ASK})
    agent = root(rig)
    first = rig.guard.authorize(agent, call("fs.write", path="/a"))
    assert first.approval_id is not None
    rig.guard.approve(first.approval_id, approver_id="reviewer-1")
    other = rig.guard.authorize(agent, call("fs.write", path="/b"))
    assert other.effect is Effect.ASK


def test_denied_approval_is_not_consumable() -> None:
    rig = Rig({"fs.write": Effect.ASK})
    agent = root(rig)
    first = rig.guard.authorize(agent, call("fs.write"))
    assert first.approval_id is not None
    rig.guard.approve(first.approval_id, approver_id="r", approve=False)
    assert rig.guard.authorize(agent, call("fs.write")).effect is Effect.ASK


def test_budget_exhaustion_denies_with_budget_source() -> None:
    rig = Rig({"fs.read": Effect.ALLOW}, max_calls=1)
    agent = root(rig)
    assert rig.guard.authorize(agent, call("fs.read")).effect is Effect.ALLOW
    second = rig.guard.authorize(agent, call("fs.read"))
    assert second.effect is Effect.DENY
    assert second.source == "budget"


def test_grant_denial_overrides_policy_allow() -> None:
    rig = Rig({"fs.write": Effect.ALLOW}, grant_denies=("fs.write",))
    child, grant = rig.guard.delegate(root(rig), "coder", tools=["fs.read"])
    decision = rig.guard.authorize(child, call("fs.write"), chain=[grant])
    assert decision.effect is Effect.DENY
    assert decision.source == "grant"
    assert rig.budgets.consumed == []


def test_grant_denial_overrides_policy_ask_without_creating_request() -> None:
    rig = Rig({"fs.write": Effect.ASK}, grant_denies=("fs.write",))
    child, grant = rig.guard.delegate(root(rig), "coder", tools=["fs.read"])
    decision = rig.guard.authorize(child, call("fs.write"), chain=[grant])
    assert decision.effect is Effect.DENY
    assert rig.approvals.pending() == []


def test_grant_can_never_turn_policy_deny_into_allow() -> None:
    rig = Rig({"fs.write": Effect.DENY})
    child, grant = rig.guard.delegate(root(rig), "coder", tools=["fs.write"])
    assert rig.guard.authorize(child, call("fs.write"), chain=[grant]).effect is Effect.DENY
    assert rig.grants.verified == []  # policy deny short-circuits


def test_delegated_agent_uses_chain_remembered_by_guard() -> None:
    rig = Rig({"fs.read": Effect.ALLOW})
    child, grant = rig.guard.delegate(root(rig), "coder", tools=["fs.read"])
    assert rig.guard.authorize(child, call("fs.read")).effect is Effect.ALLOW
    assert rig.grants.verified[0][0] == (grant,)


def test_delegated_principal_without_any_chain_is_denied() -> None:
    rig = Rig({"fs.read": Effect.ALLOW})
    forged = Principal(agent_id="x", role="coder", run_id="r", parent_id="p", depth=1)
    decision = rig.guard.authorize(forged, call("fs.read"))
    assert decision.effect is Effect.DENY
    assert decision.source == "grant"


def test_delegation_chain_grows_and_depth_increments() -> None:
    rig = Rig({"fs.read": Effect.ALLOW})
    child, _ = rig.guard.delegate(root(rig), "coder", tools=["fs.*"])
    grandchild, _ = rig.guard.delegate(child, "coder", tools=["fs.read"])
    assert (child.depth, grandchild.depth) == (1, 2)
    assert grandchild.run_id == child.run_id
    assert grandchild.parent_id == child.agent_id
    rig.guard.authorize(grandchild, call("fs.read"))
    assert len(rig.grants.verified[0][0]) == 2


def test_delegation_refused_when_decider_disallows() -> None:
    rig = Rig()
    with pytest.raises(PermissionDenied):
        rig.guard.delegate(root(rig, "coder"), "planner", tools=["*"])


def test_audit_is_called_exactly_once_per_authorize() -> None:
    rig = Rig({"fs.read": Effect.ALLOW, "fs.write": Effect.ASK})
    agent = root(rig)
    rig.guard.authorize(agent, call("fs.read"))
    rig.guard.authorize(agent, call("fs.write"))
    rig.guard.authorize(agent, call("unknown"))
    assert [e.decision.effect for e in rig.audit.entries] == [Effect.ALLOW, Effect.ASK, Effect.DENY]
    assert rig.audit.entries[1].prev_hash == rig.audit.entries[0].hash


def test_check_has_no_side_effects() -> None:
    rig = Rig({"fs.read": Effect.ALLOW, "fs.write": Effect.ASK})
    agent = root(rig)
    assert rig.guard.check(agent, call("fs.read")).effect is Effect.ALLOW
    ask = rig.guard.check(agent, call("fs.write"))
    assert ask.effect is Effect.ASK
    assert ask.approval_id is None
    assert rig.audit.entries == []
    assert rig.budgets.consumed == []
    assert rig.approvals.pending() == []


def test_check_does_not_consume_an_approval() -> None:
    rig = Rig({"fs.write": Effect.ASK})
    agent = root(rig)
    first = rig.guard.authorize(agent, call("fs.write"))
    assert first.approval_id is not None
    rig.guard.approve(first.approval_id, approver_id="r")
    rig.guard.check(agent, call("fs.write"))
    assert rig.guard.authorize(agent, call("fs.write")).effect is Effect.ALLOW


def test_check_still_reports_budget_exhaustion() -> None:
    rig = Rig({"fs.read": Effect.ALLOW}, max_calls=0)
    assert rig.guard.check(root(rig), call("fs.read")).source == "budget"


def test_start_run_creates_unique_root_principals() -> None:
    rig = Rig()
    a, b = root(rig), root(rig)
    assert a.agent_id != b.agent_id
    assert a.run_id != b.run_id
    assert (a.depth, a.on_behalf_of) == (0, "user-1")
