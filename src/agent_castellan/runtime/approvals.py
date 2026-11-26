"""Approval stores: in-memory and SQLite (WS3)."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..errors import CastellanError
from ..interfaces import Clock
from ..models import ApprovalRequest, ApprovalStatus, Principal, ToolCall
from ._common import call_hash, immediate_transaction, init_sqlite


def _may_resolve(request: ApprovalRequest, approver_id: str, approver_role: str | None) -> bool:
    """Return True if this resolver is allowed to decide the request."""
    if approver_id == request.principal.agent_id:
        return False  # an agent may never approve its own request
    kind, _, target = request.approver.partition(":")
    if kind == "role":
        return approver_role == target
    if kind == "agent":
        return approver_id == target
    return True  # "human": any resolver other than the requester


class MemoryApprovalStore:
    """Approval store held in process memory."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}
        self._status: dict[str, ApprovalStatus] = {}

    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest:
        """Open a pending approval request."""
        now = self._clock.now()
        request = ApprovalRequest(
            approval_id=f"appr-{secrets.token_hex(8)}",
            principal=principal,
            call=call,
            call_hash=call_hash(call),
            approver=approver,
            rule_id=rule_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._lock:
            self._requests[request.approval_id] = request
            self._status[request.approval_id] = ApprovalStatus.PENDING
        return request

    def resolve(
        self,
        approval_id: str,
        approver_id: str,
        approve: bool,
        *,
        approver_role: str | None = None,
    ) -> ApprovalStatus:
        """Approve or deny a pending request; unauthorized resolvers leave it pending."""
        with self._lock:
            request = self._requests.get(approval_id)
            if request is None:
                raise CastellanError(f"unknown approval id '{approval_id}'")
            status = self._status[approval_id]
            if status is not ApprovalStatus.PENDING:
                return status
            if self._clock.now() >= request.expires_at:
                self._status[approval_id] = ApprovalStatus.EXPIRED
            elif _may_resolve(request, approver_id, approver_role):
                self._status[approval_id] = (
                    ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
                )
            return self._status[approval_id]

    def consume(self, principal: Principal, call: ToolCall) -> bool:
        """Return True once if an approved, unexpired request matches this exact call."""
        digest = call_hash(call)
        now = self._clock.now()
        with self._lock:
            for approval_id, request in self._requests.items():
                if (
                    self._status[approval_id] is ApprovalStatus.APPROVED
                    and request.call_hash == digest
                    and request.principal.agent_id == principal.agent_id
                    and request.principal.run_id == principal.run_id
                    and now < request.expires_at
                ):
                    self._status[approval_id] = ApprovalStatus.CONSUMED
                    return True
        return False

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """List requests still waiting for a decision."""
        now = self._clock.now()
        with self._lock:
            return [
                r
                for i, r in self._requests.items()
                if self._status[i] is ApprovalStatus.PENDING
                and now < r.expires_at
                and (run_id is None or r.principal.run_id == run_id)
            ]


_APPROVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    call_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    request_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS approvals_lookup ON approvals (run_id, agent_id, call_hash, status);
"""


class SqliteApprovalStore:
    """Approval store persisted in SQLite; safe across threads and processes."""

    def __init__(self, path: str | Path, clock: Clock) -> None:
        self._clock = clock
        self._path = Path(path)
        init_sqlite(self._path, _APPROVAL_SCHEMA)

    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest:
        """Open a pending approval request."""
        now = self._clock.now()
        request = ApprovalRequest(
            approval_id=f"appr-{secrets.token_hex(8)}",
            principal=principal,
            call=call,
            call_hash=call_hash(call),
            approver=approver,
            rule_id=rule_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with immediate_transaction(self._path) as conn:
            conn.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.approval_id,
                    principal.run_id,
                    principal.agent_id,
                    request.call_hash,
                    ApprovalStatus.PENDING.value,
                    request.created_at.isoformat(),
                    request.expires_at.isoformat(),
                    request.model_dump_json(),
                ),
            )
        return request

    def resolve(
        self,
        approval_id: str,
        approver_id: str,
        approve: bool,
        *,
        approver_role: str | None = None,
    ) -> ApprovalStatus:
        """Approve or deny a pending request; unauthorized resolvers leave it pending."""
        with immediate_transaction(self._path) as conn:
            row = conn.execute(
                "SELECT status, request_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise CastellanError(f"unknown approval id '{approval_id}'")
            status = ApprovalStatus(row[0])
            if status is not ApprovalStatus.PENDING:
                return status
            request = ApprovalRequest.model_validate_json(row[1])
            if self._clock.now() >= request.expires_at:
                new = ApprovalStatus.EXPIRED
            elif _may_resolve(request, approver_id, approver_role):
                new = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
            else:
                return status
            conn.execute(
                "UPDATE approvals SET status = ? WHERE approval_id = ?", (new.value, approval_id)
            )
            return new

    def consume(self, principal: Principal, call: ToolCall) -> bool:
        """Return True once if an approved, unexpired request matches this exact call."""
        now = self._clock.now()
        with immediate_transaction(self._path) as conn:
            rows = conn.execute(
                "SELECT approval_id, expires_at FROM approvals "
                "WHERE run_id = ? AND agent_id = ? AND call_hash = ? AND status = ? "
                "ORDER BY created_at, rowid",
                (
                    principal.run_id,
                    principal.agent_id,
                    call_hash(call),
                    ApprovalStatus.APPROVED.value,
                ),
            ).fetchall()
            for approval_id, expires_at in rows:
                if now < datetime.fromisoformat(expires_at):
                    conn.execute(
                        "UPDATE approvals SET status = ? WHERE approval_id = ?",
                        (ApprovalStatus.CONSUMED.value, approval_id),
                    )
                    return True
        return False

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """List requests still waiting for a decision."""
        now = self._clock.now()
        query = "SELECT request_json FROM approvals WHERE status = ?"
        params: tuple[str, ...] = (ApprovalStatus.PENDING.value,)
        if run_id is not None:
            query += " AND run_id = ?"
            params = (*params, run_id)
        conn = sqlite3.connect(self._path)
        try:
            rows = conn.execute(query + " ORDER BY created_at, rowid", params).fetchall()
        finally:
            conn.close()
        requests = [ApprovalRequest.model_validate_json(r[0]) for r in rows]
        return [r for r in requests if now < r.expires_at]
