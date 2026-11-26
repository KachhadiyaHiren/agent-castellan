"""Tests for the fakes' own behaviour and the shared error types."""

from __future__ import annotations

from datetime import timedelta

import pytest

from agent_castellan import ApprovalRequired, Decision, Effect, PolicyError, Principal, ToolCall
from agent_castellan.models import ApprovalStatus
from agent_castellan.policy.conditions import build_context, compile_condition
from agent_castellan.testing.fakes import FakeApprovalStore, FrozenClock, fake_call_hash

AGENT = Principal(agent_id="a", role="coder", run_id="r")


def test_fake_call_hash_ignores_key_order() -> None:
    one = ToolCall(tool="t", args={"a": 1, "b": 2})
    two = ToolCall(tool="t", args={"b": 2, "a": 1})
    assert fake_call_hash(one) == fake_call_hash(two)


def test_frozen_clock_advances_only_on_request() -> None:
    clock = FrozenClock()
    start = clock.now()
    assert clock.now() == start
    clock.advance(5)
    assert clock.now() == start + timedelta(seconds=5)


def test_approval_expires_after_ttl() -> None:
    clock = FrozenClock()
    store = FakeApprovalStore(clock)
    request = store.create(AGENT, ToolCall(tool="t"), "rule", "human", 10)
    clock.advance(11)
    assert store.resolve(request.approval_id, "boss", True) is ApprovalStatus.EXPIRED


def test_agent_cannot_approve_its_own_request() -> None:
    store = FakeApprovalStore(FrozenClock())
    request = store.create(AGENT, ToolCall(tool="t"), "rule", "human", 10)
    assert store.resolve(request.approval_id, "a", True) is ApprovalStatus.PENDING


def test_approved_request_expires_before_consume() -> None:
    clock = FrozenClock()
    store = FakeApprovalStore(clock)
    call = ToolCall(tool="t")
    request = store.create(AGENT, call, "rule", "human", 10)
    store.resolve(request.approval_id, "boss", True)
    clock.advance(11)
    assert store.consume(AGENT, call) is False


def test_pending_filters_by_run() -> None:
    store = FakeApprovalStore(FrozenClock())
    store.create(AGENT, ToolCall(tool="t"), "rule", "human", 10)
    assert len(store.pending("r")) == 1
    assert store.pending("other") == []


def test_resolving_twice_keeps_first_outcome() -> None:
    store = FakeApprovalStore(FrozenClock())
    request = store.create(AGENT, ToolCall(tool="t"), "rule", "human", 10)
    store.resolve(request.approval_id, "boss", False)
    assert store.resolve(request.approval_id, "boss", True) is ApprovalStatus.DENIED


def test_policy_error_message_includes_location_and_rule() -> None:
    err = PolicyError("unknown operator 'lessthan'", file="team.yaml", line=42, rule_id="r1")
    assert str(err) == "team.yaml:42 rule 'r1': unknown operator 'lessthan'"


def test_approval_required_carries_id() -> None:
    err = ApprovalRequired("appr-1", Decision(effect=Effect.ASK, reason="x"))
    assert err.approval_id == "appr-1"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"args.path": {"glob": "/workspace/**"}}, True),
        ({"args.path": {"glob": "/other/**"}}, False),
        ({"args.n": {"in": [1, 2]}}, True),
        ({"agent.role": {"eq": "coder"}}, True),
        ({"args.missing": {"eq": 1}}, False),
        ({"not": {"agent.role": {"eq": "coder"}}}, False),
        ({"any": [{"agent.role": {"eq": "x"}}, {"args.n": {"eq": 1}}]}, True),
        ({"all": [{"agent.role": {"eq": "coder"}}, {"args.n": {"eq": 9}}]}, False),
    ],
)
def test_minimal_conditions(spec: dict[str, object], expected: bool) -> None:
    context = build_context(
        AGENT, ToolCall(tool="fs.read", args={"path": "/workspace/a/b", "n": 1})
    )
    assert compile_condition(spec)(context) is expected


def test_unknown_operator_is_a_policy_error() -> None:
    with pytest.raises(PolicyError):
        compile_condition({"args.x": {"lessthan": 1}})
