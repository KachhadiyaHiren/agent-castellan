"""Protocols implemented by each Castellan component."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from .models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEntry,
    Decision,
    Grant,
    Principal,
    ToolCall,
)


class PolicyDecider(Protocol):
    """Turns a call into allow, deny or ask using the loaded policy."""

    def decide(self, principal: Principal, call: ToolCall) -> Decision:
        """Return the policy decision for this call."""
        ...

    def approver_for(self, rule_id: str) -> str:
        """Return the approver string configured on a rule."""
        ...

    def can_delegate(self, parent_role: str, child_role: str, depth: int) -> bool:
        """Say whether a role at this depth may delegate to a child role."""
        ...


class GrantVerifier(Protocol):
    """Mints and verifies delegation grants."""

    def verify(
        self, chain: Sequence[Grant], principal: Principal, call: ToolCall
    ) -> Decision:  # ALLOW or DENY only
        """Check the whole grant chain against this call."""
        ...

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
        """Create a grant that can only narrow the parent's power."""
        ...


class ApprovalStore(Protocol):
    """Stores approval requests bound to the exact call they cover."""

    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest:
        """Open a pending approval request."""
        ...

    def resolve(self, approval_id: str, approver_id: str, approve: bool) -> ApprovalStatus:
        """Approve or deny a pending request."""
        ...

    def consume(self, principal: Principal, call: ToolCall) -> bool:
        """Return True once if an approved, unexpired request matches this exact call."""
        ...

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """List requests still waiting for a decision."""
        ...


class BudgetTracker(Protocol):
    """Counts calls and cost across the run tree."""

    def precheck(self, principal: Principal, call: ToolCall) -> Decision | None:
        """Return None when within budget, else a DENY decision with source budget."""
        ...

    def consume(self, principal: Principal, call: ToolCall) -> None:
        """Record one allowed call against every applicable budget."""
        ...

    def usage(self, run_id: str) -> dict[str, float]:
        """Return the counters recorded for a run."""
        ...


class AuditSink(Protocol):
    """Append-only record of every decision."""

    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry:
        """Record one decision and return the stored entry."""
        ...


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current time (timezone-aware, UTC)."""
        ...
