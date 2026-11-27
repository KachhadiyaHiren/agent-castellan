"""Public value types shared by every Castellan component."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Effect(str, Enum):
    """What a rule or decision says should happen to a tool call.

    Attributes:
        ALLOW: The call may run.
        DENY: The call must not run.
        ASK: The call may run only after an approver says yes.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class Principal(BaseModel):
    """An agent identity within one run.

    A principal is immutable. Create the root one with `Guard.start_run` and child ones
    with `Guard.delegate`; you rarely build one by hand.

    Attributes:
        agent_id: Unique id of this agent instance.
        role: Role name, as used in `agents:` and in rule `agents:` lists.
        run_id: Id shared by every agent in one delegation tree.
        parent_id: `agent_id` of the agent that delegated to this one, if any.
        parent_role: Role of that parent, if any.
        depth: Distance from the root agent; the root has depth 0.
        on_behalf_of: Id of the end user the whole run acts for, if any.
    """

    model_config = ConfigDict(frozen=True)
    agent_id: str
    role: str
    run_id: str
    parent_id: str | None = None
    parent_role: str | None = None
    depth: int = 0  # root agent = 0
    on_behalf_of: str | None = None  # end-user id


class ToolCall(BaseModel):
    """The thing being authorized: one tool invocation with its arguments.

    Attributes:
        tool: Namespaced tool name such as `fs.write` or `mcp:filesystem/read_file`.
            Names are lower-cased and checked before any rule is evaluated.
        args: JSON-serializable arguments the tool will receive.
        resource: Optional extra attributes about the target; kept in the audit log.
        cost_units: Cost of this call, counted against `max_cost_units` budgets.
    """

    model_config = ConfigDict(frozen=True)
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    cost_units: float = 0.0


class TraceStep(BaseModel):
    """One rule considered during a decision, and why it did or did not match.

    Attributes:
        rule_id: Id of the rule that was considered.
        matched: True if the rule's `agents`, `tools` and `when` all matched.
        detail: Short reason, such as `tools: no match for 'fs.write'`.
    """

    model_config = ConfigDict(frozen=True)
    rule_id: str
    matched: bool
    detail: str  # e.g. "tools: no match for 'fs.write'"


class Decision(BaseModel):
    """The outcome of authorizing a tool call.

    Attributes:
        effect: `allow`, `deny` or `ask`.
        reason: Human-readable explanation, taken from the rule's `reason` when it has one.
        rule_id: Id of the winning rule, or `None` when a default, grant or budget decided.
        source: Which part of the pipeline decided: `policy`, `default`, `grant`,
            `budget`, `approval` or `invalid`.
        trace: One step per rule considered, in file order.
        approval_id: Id of the pending approval request when `effect` is `ask`.
    """

    model_config = ConfigDict(frozen=True)
    effect: Effect
    reason: str
    rule_id: str | None = None
    source: str = "policy"  # policy | grant | budget | approval | default | invalid
    trace: tuple[TraceStep, ...] = ()
    approval_id: str | None = None


class Grant(BaseModel):
    """A signed delegation from a parent agent to a child agent.

    Grants form a chain from the root to the acting agent. Each grant can only narrow
    the one before it.

    Attributes:
        grant_id: Unique id of this grant.
        issuer_agent_id: Agent that issued the grant (the parent).
        subject_agent_id: Agent that receives the grant (the child).
        subject_role: Role of the child.
        run_id: Run the grant belongs to; it is useless in any other run.
        tools: Tool globs the child may use, always a subset of the parent's.
        when: Extra conditions, in the same language as a rule's `when`.
        expires_at: Moment after which the grant stops working.
        max_calls: Maximum calls allowed under this grant, or `None` for no limit.
        signature: Hex HMAC that chains this grant to the ones before it.
    """

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
    """A pending request for a human or agent to approve one exact call.

    Attributes:
        approval_id: Id to pass to `Guard.approve`.
        principal: The agent that asked.
        call: The call that needs approval.
        call_hash: SHA-256 of the normalized tool name and arguments; an approval only
            unlocks a call with this exact hash.
        approver: Who may approve: `human`, `role:<role>` or `agent:<id>`.
        rule_id: The `ask` rule that created the request.
        created_at: When the request was created.
        expires_at: When the request stops being usable.
    """

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
    """Lifecycle state of an approval request.

    A request starts as `PENDING`, becomes `APPROVED`, `DENIED` or `EXPIRED`, and an
    approved request becomes `CONSUMED` the one time it unlocks a call.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class AuditEntry(BaseModel):
    """One hash-chained record in the audit log.

    Attributes:
        seq: Position in the log, starting at 0.
        at: When the decision was recorded (UTC).
        principal: The agent that made the call.
        call: The normalized call.
        decision: What the guard decided.
        prev_hash: `hash` of the previous entry; 64 zeros for the first entry.
        hash: SHA-256 over `prev_hash` and this entry's canonical JSON.
    """

    model_config = ConfigDict(frozen=True)
    seq: int
    at: datetime
    principal: Principal
    call: ToolCall
    decision: Decision
    prev_hash: str
    hash: str
