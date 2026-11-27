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
    """The single entry point: runs every tool call through the full authorization pipeline.

    A guard wires together a policy, a grant verifier, an approval store, a budget tracker
    and an audit log. Most users build one with `Guard.from_file`.

    Example:
        ```python
        guard = Guard.from_file("policy.yaml", key=secrets.token_bytes(32))
        me = guard.start_run("planner")
        decision = guard.authorize(me, ToolCall(tool="fs.read", args={"path": "/workspace/a"}))
        ```

    Args:
        decider: Policy engine that answers allow, deny or ask.
        grants: Verifier and minter for delegation grants.
        approvals: Store of approval requests.
        budgets: Tracker of run, role and grant limits.
        audit: Sink that records every `authorize` decision.
        clock: Source of the current time.
        approval_ttl: Seconds an approval request stays valid.
    """

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
        """Build a guard with the real components from a policy file.

        Args:
            policy_path: Path of the policy YAML file.
            key: Root key (at least 32 bytes) used to sign grants. When omitted, the
                hex-encoded `CASTELLAN_KEY` environment variable is used; if that is
                unset too, a random key is generated for this process and a
                `RuntimeWarning` is emitted.
            state_path: SQLite file for approvals and budgets. When omitted, both live in
                memory and vanish when the process ends. Set it to share state between
                processes, for example with `castellan approve`.

        Returns:
            A fully wired guard. The audit log is written to the policy's `audit.path`.

        Raises:
            PolicyError: The policy file cannot be read or is invalid.
            GrantError: The key is shorter than 32 bytes or `CASTELLAN_KEY` is not hex.
        """
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
        """Create the root principal of a new run.

        Args:
            role: Role of the root agent, for example `planner`.
            on_behalf_of: Id of the end user the run acts for; copied to every child.

        Returns:
            A principal with depth 0 and a fresh `run_id`.
        """
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
        """Create a child principal and the grant that bounds its power.

        The child can never do more than the parent: `tools` must be covered by the
        parent's own grant, and expiry and `max_calls` can only shrink.

        Args:
            parent: The delegating agent.
            child_role: Role of the new agent.
            tools: Tool globs the child may use, for example `["fs.read", "web.*"]`.
            when: Extra conditions in the rule `when` language, ANDed with the parent's.
            ttl_seconds: Lifetime of the grant in seconds. A child grant may not outlive
                its parent's, so when you delegate again from a delegated agent, pass a
                value smaller than the time its own grant has left.
            max_calls: Optional cap on calls made under this grant. The value is stored
                and signed in the grant, but the guard does not yet count calls against
                it; use the policy `budgets` section to cap usage today.

        Returns:
            The child principal and its signed grant. Pass the grant (or the chain)
            to `authorize`, or let the guard remember it for you.

        Raises:
            PermissionDenied: The policy does not let `parent.role` delegate to
                `child_role` at this depth.
            GrantError: The request would widen the parent's power.
        """
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
        """Decide one call, record it, and count it if it was allowed.

        The pipeline is: budget precheck, policy decision, grant chain check, approval,
        audit append, then budget consume (only when the final answer is allow).

        Args:
            principal: The agent making the call.
            call: The tool call to authorize.
            chain: Grants from the root to `principal`. Optional for agents created by
                this guard's `delegate`, which remembers the chain.

        Returns:
            The final decision. When `effect` is `ask`, `approval_id` names the new
            request; retry the same call after it is approved.
        """
        decision = self._evaluate(principal, call, chain, create_approval=True)
        self._audit.append(principal, call, decision)
        if decision.effect is Effect.ALLOW:
            self._budgets.consume(principal, call)
        return decision

    def check(
        self, principal: Principal, call: ToolCall, *, chain: Sequence[Grant] = ()
    ) -> Decision:
        """Dry run: decide a call without any side effect.

        Nothing is written to the audit log, no budget is used and no approval is created
        or consumed. Use it to ask "would this be allowed?".

        Args:
            principal: The agent making the call.
            call: The tool call to check.
            chain: Grants from the root to `principal`; see `authorize`.

        Returns:
            The decision `authorize` would reach, except that an `ask` has no `approval_id`
            and an already-approved call still shows as `ask`.
        """
        return self._evaluate(principal, call, chain, create_approval=False)

    def approve(
        self, approval_id: str, *, approver_id: str, approve: bool = True
    ) -> ApprovalStatus:
        """Approve or deny a pending request on behalf of an approver.

        Args:
            approval_id: Id from the `ask` decision.
            approver_id: Who is answering. It must satisfy the rule's `approver` and must
                not be the agent that asked.
            approve: True to approve, False to deny.

        Returns:
            The new status of the request. If the approver is not allowed to answer (the
            requester itself, or someone the rule's `approver` does not name), the request
            stays `PENDING` and no error is raised. Today only `human` and `agent:<id>`
            approvers can be satisfied through this method; `role:<role>` approvers cannot.

        Raises:
            CastellanError: `approval_id` is unknown.
        """
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
