"""PolicyEngine implementing interfaces.PolicyDecider (WS1)."""

from __future__ import annotations

from ..models import Decision, Principal, ToolCall
from .schema import Policy


class PolicyEngine:
    """Decides calls according to a loaded Policy."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def decide(self, principal: Principal, call: ToolCall) -> Decision:
        """Return the policy decision for this call."""
        raise NotImplementedError

    def approver_for(self, rule_id: str) -> str:
        """Return the approver string configured on a rule."""
        raise NotImplementedError

    def can_delegate(self, parent_role: str, child_role: str, depth: int) -> bool:
        """Say whether a role at this depth may delegate to a child role."""
        raise NotImplementedError
