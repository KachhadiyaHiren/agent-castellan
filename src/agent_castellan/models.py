"""Public value types shared by every Castellan component."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Effect(str, Enum):
    """What a rule or decision says should happen to a tool call."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class Principal(BaseModel):
    """An agent identity within one run."""

    model_config = ConfigDict(frozen=True)
    agent_id: str
    role: str
    run_id: str
    parent_id: str | None = None
    parent_role: str | None = None
    depth: int = 0  # root agent = 0
    on_behalf_of: str | None = None  # end-user id


class ToolCall(BaseModel):
    """The thing being authorized."""

    model_config = ConfigDict(frozen=True)
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    cost_units: float = 0.0


class TraceStep(BaseModel):
    """One rule considered during a decision, and why it did or did not match."""

    model_config = ConfigDict(frozen=True)
    rule_id: str
    matched: bool
    detail: str  # e.g. "tools: no match for 'fs.write'"


class Decision(BaseModel):
    """The outcome of authorizing a tool call."""

    model_config = ConfigDict(frozen=True)
    effect: Effect
    reason: str
    rule_id: str | None = None
    source: str = "policy"  # policy | grant | budget | approval | default | invalid
    trace: tuple[TraceStep, ...] = ()
    approval_id: str | None = None


class Grant(BaseModel):
    """A signed delegation from a parent agent to a child agent."""

    model_config = ConfigDict(frozen=True)
    grant_id: str
    issuer_agent_id: str
    subject_agent_id: str
    subject_role: str
    run_id: str
    tools: tuple[str, ...]  # globs, must be ⊆ issuer's effective tools
    when: dict[str, Any] | None = None  # extra conditions, same DSL as rules
    expires_at: datetime
    max_calls: int | None = None
    signature: str  # hex HMAC, chained (see PLAN.md §5.2)


class ApprovalRequest(BaseModel):
    """A pending request for a human or agent to approve one exact call."""

    model_config = ConfigDict(frozen=True)
    approval_id: str
    principal: Principal
    call: ToolCall
    call_hash: str
    approver: str
    rule_id: str
    created_at: datetime
    expires_at: datetime


class ApprovalStatus(str, Enum):
    """Lifecycle state of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class AuditEntry(BaseModel):
    """One hash-chained record in the audit log."""

    model_config = ConfigDict(frozen=True)
    seq: int
    at: datetime
    principal: Principal
    call: ToolCall
    decision: Decision
    prev_hash: str
    hash: str
