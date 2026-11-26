"""Approval stores: in-memory and SQLite (WS3)."""

from __future__ import annotations

from pathlib import Path

from ..interfaces import Clock
from ..models import ApprovalRequest, ApprovalStatus, Principal, ToolCall


class MemoryApprovalStore:
    """Approval store held in process memory."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest:
        """Open a pending approval request."""
        raise NotImplementedError

    def resolve(self, approval_id: str, approver_id: str, approve: bool) -> ApprovalStatus:
        """Approve or deny a pending request."""
        raise NotImplementedError

    def consume(self, principal: Principal, call: ToolCall) -> bool:
        """Return True once if an approved, unexpired request matches this exact call."""
        raise NotImplementedError

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """List requests still waiting for a decision."""
        raise NotImplementedError


class SqliteApprovalStore(MemoryApprovalStore):
    """Approval store persisted in SQLite."""

    def __init__(self, path: str | Path, clock: Clock) -> None:
        super().__init__(clock)
        self._path = Path(path)
