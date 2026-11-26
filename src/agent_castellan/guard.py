"""Guard: the single entry point that runs the full authorization pipeline."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import PermissionDenied
from .interfaces import (
    ApprovalStore,
    AuditSink,
    BudgetTracker,
    Clock,
    GrantVerifier,
    PolicyDecider,
)
from .models import ApprovalStatus, Decision, Effect, Grant, Principal, ToolCall


class SystemClock:
    """Clock backed by the system time in UTC."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)


class Guard:
    """Orchestrates budgets, policy, grants, approvals and audit for each tool call."""

    def __init__(
        self,
        decider: PolicyDecider,
        grants: GrantVerifier,
        approvals: ApprovalStore,
        budgets: BudgetTracker,
        audit: AuditSink,
        clock: Clock,
        approval_ttl: int = 600,
    ) -> None:
        self._decider = decider
        self._grants = grants
        self._approvals = approvals
        self._budgets = budgets
        self._audit = audit
        self._clock = clock
        self._approval_ttl = approval_ttl
        self._chains: dict[str, tuple[Grant, ...]] = {}

    @classmethod
    def from_file(
        cls,
        policy_path: str | Path,
        *,
        key: bytes | None = None,
        state_path: str | Path | None = None,
    ) -> Guard:
        """Wire the real components from a policy file (imports are lazy)."""
        from .audit.log import AuditLog
        from .delegation.chain import ChainVerifier
        from .delegation.keys import load_root_key
        from .policy.engine import PolicyEngine
        from .policy.loader import load_policy
        from .runtime.approvals import MemoryApprovalStore, SqliteApprovalStore
        from .runtime.budgets import MemoryBudgetTracker, SqliteBudgetTracker

        policy = load_policy(policy_path)
        clock = SystemClock()
        approvals: ApprovalStore
        budgets: BudgetTracker
        if state_path is None:
            approvals = MemoryApprovalStore(clock)
            budgets = MemoryBudgetTracker(policy.budgets)
        else:
            approvals = SqliteApprovalStore(state_path, clock)
            budgets = SqliteBudgetTracker(policy.budgets, state_path)
        return cls(
            decider=PolicyEngine(policy),
            grants=ChainVerifier(load_root_key(key), clock),
            approvals=approvals,
            budgets=budgets,
            audit=AuditLog(policy.audit.path, clock),
            clock=clock,
            approval_ttl=policy.approvals.ttl_seconds,
        )

    def start_run(self, role: str, *, on_behalf_of: str | None = None) -> Principal:
        """Create the root principal of a new run."""
        return Principal(
            agent_id=f"agent-{secrets.token_hex(6)}",
            role=role,
            run_id=f"run-{secrets.token_hex(8)}",
            depth=0,
            on_behalf_of=on_behalf_of,
        )

    def delegate(
        self,
        parent: Principal,
        child_role: str,
        *,
        tools: Sequence[str],
        when: dict[str, Any] | None = None,
        ttl_seconds: int = 900,
        max_calls: int | None = None,
    ) -> tuple[Principal, Grant]:
        """Create a child principal and the grant that bounds its power."""
        if not self._decider.can_delegate(parent.role, child_role, parent.depth):
            raise PermissionDenied(
                Decision(
                    effect=Effect.DENY,
                    reason=f"role '{parent.role}' may not delegate to '{child_role}' "
                    f"at depth {parent.depth}",
                    source="policy",
                )
            )
        child = Principal(
            agent_id=f"agent-{secrets.token_hex(6)}",
            role=child_role,
            run_id=parent.run_id,
            parent_id=parent.agent_id,
            parent_role=parent.role,
            depth=parent.depth + 1,
            on_behalf_of=parent.on_behalf_of,
        )
        parent_chain = self._chains.get(parent.agent_id, ())
        grant = self._grants.mint(parent, parent_chain, child, tools, when, ttl_seconds, max_calls)
        self._chains[child.agent_id] = (*parent_chain, grant)
        return child, grant

    def authorize(
        self, principal: Principal, call: ToolCall, *, chain: Sequence[Grant] = ()
    ) -> Decision:
        """Run the full pipeline: budget, policy, grants, approval, audit, then consume."""
        decision = self._evaluate(principal, call, chain, create_approval=True)
        self._audit.append(principal, call, decision)
        if decision.effect is Effect.ALLOW:
            self._budgets.consume(principal, call)
        return decision

    def check(
        self, principal: Principal, call: ToolCall, *, chain: Sequence[Grant] = ()
    ) -> Decision:
        """Dry run: no audit, no budget use and no approval created or consumed."""
        return self._evaluate(principal, call, chain, create_approval=False)

    def approve(
        self, approval_id: str, *, approver_id: str, approve: bool = True
    ) -> ApprovalStatus:
        """Approve or deny a pending request on behalf of an approver."""
        return self._approvals.resolve(approval_id, approver_id, approve)

    def _evaluate(  # noqa: PLR0911
        self,
        principal: Principal,
        call: ToolCall,
        chain: Sequence[Grant],
        *,
        create_approval: bool,
    ) -> Decision:
        blocked = self._budgets.precheck(principal, call)
        if blocked is not None:
            return blocked

        decision = self._decider.decide(principal, call)
        if decision.effect is Effect.DENY:
            return decision

        grant_chain = tuple(chain) or self._chains.get(principal.agent_id, ())
        if grant_chain or principal.depth > 0:
            if not grant_chain:
                return Decision(
                    effect=Effect.DENY,
                    reason="delegated agent presented no grant chain",
                    source="grant",
                    trace=decision.trace,
                )
            grant_result = self._grants.verify(grant_chain, principal, call)
            if grant_result.effect is not Effect.ALLOW:
                return grant_result.model_copy(
                    update={"effect": Effect.DENY, "trace": decision.trace}
                )

        if decision.effect is not Effect.ASK:
            return decision

        if not create_approval:
            return decision
        if self._approvals.consume(principal, call):
            return Decision(
                effect=Effect.ALLOW,
                reason=f"approved request for rule '{decision.rule_id}'",
                rule_id=decision.rule_id,
                source="approval",
                trace=decision.trace,
            )
        rule_id = decision.rule_id or "default"
        request = self._approvals.create(
            principal,
            call,
            rule_id,
            self._decider.approver_for(rule_id) if decision.rule_id else "human",
            self._approval_ttl,
        )
        return decision.model_copy(update={"approval_id": request.approval_id})
