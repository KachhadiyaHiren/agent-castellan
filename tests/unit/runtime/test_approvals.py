"""Approval store behaviour, run against both backends."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_castellan.errors import CastellanError
from agent_castellan.interfaces import ApprovalStore
from agent_castellan.models import ApprovalStatus, Principal, ToolCall
from agent_castellan.runtime.approvals import MemoryApprovalStore, SqliteApprovalStore
from agent_castellan.testing.fakes import FrozenClock

Factory = Callable[[], ApprovalStore]


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture(params=["memory", "sqlite"])
def factory(request: pytest.FixtureRequest, clock: FrozenClock, tmp_path: Path) -> Factory:
    if request.param == "memory":
        store = MemoryApprovalStore(clock)
        return lambda: store
    return lambda: SqliteApprovalStore(tmp_path / "state.db", clock)


@pytest.fixture
def store(factory: Factory) -> ApprovalStore:
    return factory()


CODER = Principal(agent_id="a-coder", role="coder", run_id="r1", depth=1)
CALL = ToolCall(tool="fs.write", args={"path": "/w/a.py", "content": "x"})


def _create(store: ApprovalStore, approver: str = "human", ttl: int = 60):  # type: ignore[no-untyped-def]
    return store.create(CODER, CALL, "rule-1", approver, ttl)


def test_create_is_pending_and_bound_to_call_hash(store: ApprovalStore) -> None:
    req = _create(store)
    assert len(req.call_hash) == 64
    assert req.approver == "human"
    assert store.pending() == [req]


def test_call_hash_ignores_arg_order(store: ApprovalStore) -> None:
    a = store.create(CODER, ToolCall(tool="t", args={"a": 1, "b": 2}), "r", "human", 60)
    b = store.create(CODER, ToolCall(tool="t", args={"b": 2, "a": 1}), "r", "human", 60)
    assert a.call_hash == b.call_hash


def test_approved_request_is_consumed_exactly_once(store: ApprovalStore) -> None:
    req = _create(store)
    assert store.resolve(req.approval_id, "human-1", True) is ApprovalStatus.APPROVED
    assert store.consume(CODER, CALL) is True
    assert store.consume(CODER, CALL) is False


def test_pending_request_cannot_be_consumed(store: ApprovalStore) -> None:
    _create(store)
    assert store.consume(CODER, CALL) is False


def test_denied_request_cannot_be_consumed(store: ApprovalStore) -> None:
    req = _create(store)
    assert store.resolve(req.approval_id, "human-1", False) is ApprovalStatus.DENIED
    assert store.consume(CODER, CALL) is False
    assert store.pending() == []


def test_approval_does_not_cover_different_args(store: ApprovalStore) -> None:
    req = _create(store)
    store.resolve(req.approval_id, "human-1", True)
    other = ToolCall(tool="fs.write", args={"path": "/w/b.py", "content": "x"})
    assert store.consume(CODER, other) is False
    assert store.consume(CODER, CALL) is True


def test_approval_is_bound_to_the_requesting_agent_and_run(store: ApprovalStore) -> None:
    req = _create(store)
    store.resolve(req.approval_id, "human-1", True)
    other_agent = CODER.model_copy(update={"agent_id": "a-other"})
    other_run = CODER.model_copy(update={"run_id": "r2"})
    assert store.consume(other_agent, CALL) is False
    assert store.consume(other_run, CALL) is False
    assert store.consume(CODER, CALL) is True


def test_self_approval_is_refused(store: ApprovalStore) -> None:
    req = _create(store)
    assert store.resolve(req.approval_id, CODER.agent_id, True) is ApprovalStatus.PENDING
    assert store.consume(CODER, CALL) is False


def test_role_approver_requires_matching_role(store: ApprovalStore) -> None:
    req = _create(store, approver="role:reviewer")
    assert store.resolve(req.approval_id, "a-x", True) is ApprovalStatus.PENDING
    assert (
        store.resolve(req.approval_id, "a-x", True, approver_role="coder")  # type: ignore[call-arg]
        is ApprovalStatus.PENDING
    )
    assert (
        store.resolve(req.approval_id, "a-x", True, approver_role="reviewer")  # type: ignore[call-arg]
        is ApprovalStatus.APPROVED
    )


def test_agent_approver_requires_that_agent(store: ApprovalStore) -> None:
    req = _create(store, approver="agent:a-boss")
    assert store.resolve(req.approval_id, "a-x", True) is ApprovalStatus.PENDING
    assert store.resolve(req.approval_id, "a-boss", True) is ApprovalStatus.APPROVED


def test_expired_pending_request_cannot_be_approved(
    store: ApprovalStore, clock: FrozenClock
) -> None:
    req = _create(store, ttl=10)
    clock.advance(10)
    assert store.pending() == []
    assert store.resolve(req.approval_id, "human-1", True) is ApprovalStatus.EXPIRED
    assert store.consume(CODER, CALL) is False


def test_approved_request_expires_before_use(store: ApprovalStore, clock: FrozenClock) -> None:
    req = _create(store, ttl=10)
    store.resolve(req.approval_id, "human-1", True)
    clock.advance(11)
    assert store.consume(CODER, CALL) is False


def test_resolved_request_status_is_final(store: ApprovalStore) -> None:
    req = _create(store)
    store.resolve(req.approval_id, "human-1", False)
    assert store.resolve(req.approval_id, "human-2", True) is ApprovalStatus.DENIED


def test_unknown_approval_id_raises(store: ApprovalStore) -> None:
    with pytest.raises(CastellanError, match="unknown approval"):
        store.resolve("nope", "human-1", True)


def test_pending_filters_by_run(store: ApprovalStore) -> None:
    mine = _create(store)
    other = CODER.model_copy(update={"run_id": "r2", "agent_id": "a-2"})
    store.create(other, CALL, "rule-1", "human", 60)
    assert store.pending("r1") == [mine]
    assert len(store.pending()) == 2


def test_two_approved_requests_are_consumed_one_at_a_time(store: ApprovalStore) -> None:
    for _ in range(2):
        store.resolve(_create(store).approval_id, "human-1", True)
    assert [store.consume(CODER, CALL) for _ in range(3)] == [True, True, False]


def test_consume_exactly_once_across_threads(store: ApprovalStore) -> None:
    store.resolve(_create(store).approval_id, "human-1", True)
    wins: list[bool] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        wins.append(store.consume(CODER, CALL))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1


def test_sqlite_state_is_shared_between_connections(clock: FrozenClock, tmp_path: Path) -> None:
    first = SqliteApprovalStore(tmp_path / "s.db", clock)
    second = SqliteApprovalStore(tmp_path / "s.db", clock)
    req = first.create(CODER, CALL, "rule-1", "human", 60)
    assert second.pending() == [req]
    second.resolve(req.approval_id, "human-1", True)
    assert first.consume(CODER, CALL) is True
    assert second.consume(CODER, CALL) is False
