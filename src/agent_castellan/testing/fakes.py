"""In-memory fakes of every interface, for tests that must not depend on real components."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ..models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEntry,
    Decision,
    Effect,
    Grant,
    Principal,
    ToolCall,
)

EPOCH = datetime(2030, 1, 1, tzinfo=UTC)


class FrozenClock:
    """Clock that only moves when told to."""

    def __init__(self, now: datetime = EPOCH) -> None:
        self._now = now

    def now(self) -> datetime:
        """Return the frozen time."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self._now += timedelta(seconds=seconds)


def fake_call_hash(call: ToolCall) -> str:
    """Hash `{tool, args}` canonically (the fakes' stand-in for the real normalizer)."""
    payload = json.dumps(
        {"tool": call.tool, "args": call.args},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class FakeDecider:
    """Decides by exact tool name from a dict; unlisted tools get `default`."""

    def __init__(
        self,
        effects: Mapping[str, Effect] | None = None,
        *,
        default: Effect = Effect.DENY,
        approver: str = "human",
        delegations: Mapping[str, Sequence[str]] | None = None,
        max_depth: int = 2,
    ) -> None:
        self.effects = dict(effects or {})
        self.default = default
        self.approver = approver
        self.delegations = {k: tuple(v) for k, v in (delegations or {}).items()}
        self.max_depth = max_depth

    def decide(self, principal: Principal, call: ToolCall) -> Decision:
        """Return the configured effect for the tool."""
        if call.tool in self.effects:
            return Decision(
                effect=self.effects[call.tool], reason="fake rule", rule_id=f"rule:{call.tool}"
            )
        return Decision(effect=self.default, reason="fake default", source="default")

    def approver_for(self, rule_id: str) -> str:
        """Return the configured approver."""
        return self.approver

    def can_delegate(self, parent_role: str, child_role: str, depth: int) -> bool:
        """Allow delegation listed in `delegations` while depth is below `max_depth`."""
        return child_role in self.delegations.get(parent_role, ()) and depth < self.max_depth


class FakeGrantVerifier:
    """Mints unsigned grants; verify allows unless the tool is in `deny_tools`."""

    def __init__(self, clock: FrozenClock, deny_tools: Sequence[str] = ()) -> None:
        self.clock = clock
        self.deny_tools = set(deny_tools)
        self.verified: list[tuple[tuple[Grant, ...], ToolCall]] = []
        self._counter = 0

    def verify(self, chain: Sequence[Grant], principal: Principal, call: ToolCall) -> Decision:
        """Allow unless the tool is listed as denied."""
        self.verified.append((tuple(chain), call))
        if call.tool in self.deny_tools:
            return Decision(effect=Effect.DENY, reason="fake grant denies tool", source="grant")
        return Decision(effect=Effect.ALLOW, reason="fake grant ok", source="grant")

    def mint(
        self,
        parent: Principal,
        parent_chain: Sequence[Grant],
        child: Principal,
        tools: Sequence[str],
        when: dict[str, Any] | None,
        ttl_seconds: int,
        max_calls: int | None,
    ) -> Grant:
        """Create a grant with a dummy signature."""
        self._counter += 1
        return Grant(
            grant_id=f"grant-{self._counter}",
            issuer_agent_id=parent.agent_id,
            subject_agent_id=child.agent_id,
            subject_role=child.role,
            run_id=child.run_id,
            tools=tuple(tools),
            when=when,
            expires_at=self.clock.now() + timedelta(seconds=ttl_seconds),
            max_calls=max_calls,
            signature="fake",
        )


class FakeApprovalStore:
    """Dict-backed approval store with the real status transitions."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.requests: dict[str, ApprovalRequest] = {}
        self.status: dict[str, ApprovalStatus] = {}
        self._counter = 0

    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest:
        """Open a pending request."""
        self._counter += 1
        now = self.clock.now()
        request = ApprovalRequest(
            approval_id=f"appr-{self._counter}",
            principal=principal,
            call=call,
            call_hash=fake_call_hash(call),
            approver=approver,
            rule_id=rule_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self.requests[request.approval_id] = request
        self.status[request.approval_id] = ApprovalStatus.PENDING
        return request

    def resolve(self, approval_id: str, approver_id: str, approve: bool) -> ApprovalStatus:
        """Approve or deny; self-approval is refused (left pending)."""
        request = self.requests[approval_id]
        if self.status[approval_id] is not ApprovalStatus.PENDING:
            return self.status[approval_id]
        if self.clock.now() >= request.expires_at:
            self.status[approval_id] = ApprovalStatus.EXPIRED
        elif approver_id == request.principal.agent_id:
            return ApprovalStatus.PENDING
        else:
            self.status[approval_id] = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        return self.status[approval_id]

    def consume(self, principal: Principal, call: ToolCall) -> bool:
        """Consume one matching approved, unexpired request."""
        digest = fake_call_hash(call)
        for approval_id, request in self.requests.items():
            if (
                self.status[approval_id] is ApprovalStatus.APPROVED
                and request.call_hash == digest
                and request.principal.agent_id == principal.agent_id
                and self.clock.now() < request.expires_at
            ):
                self.status[approval_id] = ApprovalStatus.CONSUMED
                return True
        return False

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """List pending requests, optionally for one run."""
        return [
            r
            for i, r in self.requests.items()
            if self.status[i] is ApprovalStatus.PENDING
            and (run_id is None or r.principal.run_id == run_id)
        ]


class FakeBudgetTracker:
    """Counts calls per run and denies once `max_calls` is reached."""

    def __init__(self, max_calls: int | None = None) -> None:
        self.max_calls = max_calls
        self.counts: dict[str, float] = {}
        self.consumed: list[ToolCall] = []

    def precheck(self, principal: Principal, call: ToolCall) -> Decision | None:
        """Deny when the run has used its calls."""
        if self.max_calls is not None and self.counts.get(principal.run_id, 0) >= self.max_calls:
            return Decision(effect=Effect.DENY, reason="run budget exhausted", source="budget")
        return None

    def consume(self, principal: Principal, call: ToolCall) -> None:
        """Count one call."""
        self.counts[principal.run_id] = self.counts.get(principal.run_id, 0) + 1
        self.consumed.append(call)

    def usage(self, run_id: str) -> dict[str, float]:
        """Return the call counter for a run."""
        return {"tool_calls": self.counts.get(run_id, 0)}


class FakeAuditSink:
    """Keeps entries in a list with a simple hash chain."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.entries: list[AuditEntry] = []

    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry:
        """Store one entry."""
        prev = self.entries[-1].hash if self.entries else "0" * 64
        seq = len(self.entries)
        digest = hashlib.sha256(f"{prev}{seq}{call.tool}{decision.effect.value}".encode())
        entry = AuditEntry(
            seq=seq,
            at=self.clock.now(),
            principal=principal,
            call=call,
            decision=decision,
            prev_hash=prev,
            hash=digest.hexdigest(),
        )
        self.entries.append(entry)
        return entry
