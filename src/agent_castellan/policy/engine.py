"""PolicyEngine implementing interfaces.PolicyDecider (WS1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache

from ..errors import PolicyError
from ..interfaces import Clock
from ..models import Decision, Effect, Principal, ToolCall, TraceStep
from .conditions import Condition, build_context, compile_condition, referenced_paths
from .matching import compile_tool_matcher
from .normalize import normalize_call
from .schema import Policy, Rule


@lru_cache(maxsize=8192)
def _step(rule_id: str, matched: bool, detail: str) -> TraceStep:
    """Build (and share) trace steps: they are immutable and highly repetitive."""
    return TraceStep(rule_id=rule_id, matched=matched, detail=detail)


class _UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _CompiledRule:
    __slots__ = ("any_role", "condition", "roles", "rule", "tools")

    def __init__(self, rule: Rule, source: str | None) -> None:
        self.rule = rule
        self.any_role = "*" in rule.agents
        self.roles = frozenset(rule.agents)
        try:
            self.tools = compile_tool_matcher(rule.tools)
            self.condition: Condition | None = (
                compile_condition(rule.when) if rule.when is not None else None
            )
        except PolicyError as exc:
            raise PolicyError(exc.message, file=source, line=rule.line, rule_id=rule.id) from exc


class PolicyEngine:
    """Decides calls according to a loaded Policy (PLAN.md §2)."""

    def __init__(
        self,
        policy: Policy,
        *,
        clock: Clock | None = None,
        run_tool_calls: Callable[[str], int] | None = None,
    ) -> None:
        self.policy = policy
        self._clock: Clock = clock or _UtcClock()
        self._run_tool_calls = run_tool_calls
        self._rules = tuple(_CompiledRule(rule, policy.source) for rule in policy.rules)
        self._by_id: dict[str, Rule] = {}
        for rule in policy.rules:
            self._by_id.setdefault(rule.id, rule)
        paths = [path for rule in policy.rules if rule.when for path in referenced_paths(rule.when)]
        self._needs_time = any(path.startswith("time.") for path in paths)
        self._needs_run = "run.tool_calls" in paths

    def decide(self, principal: Principal, call: ToolCall) -> Decision:
        """Return the policy decision for this call."""
        try:
            call = normalize_call(call)
        except PolicyError as exc:
            return Decision(
                effect=Effect.DENY,
                reason="invalid_call",
                source="invalid",
                trace=(TraceStep(rule_id="<normalize>", matched=False, detail=exc.message),),
            )

        role = principal.role
        tool = call.tool
        context: dict[str, object] | None = None
        trace: list[TraceStep] = []
        best: dict[Effect, Rule] = {}
        for compiled in self._rules:
            rule = compiled.rule
            if not (compiled.any_role or role in compiled.roles):
                detail = f"agents: no match for role '{role}'"
            elif not compiled.tools(tool):
                detail = f"tools: no match for '{tool}'"
            else:
                detail = ""
                if compiled.condition is not None:
                    if context is None:
                        context = self._context(principal, call)
                    if not compiled.condition(context):
                        detail = "when: condition is false"
            matched = not detail
            trace.append(_step(rule.id, matched, detail or "matched"))
            if matched:
                current = best.get(rule.effect)
                if current is None or rule.priority > current.priority:
                    best[rule.effect] = rule

        steps = tuple(trace)
        for effect in (Effect.DENY, Effect.ASK, Effect.ALLOW):
            winner = best.get(effect)
            if winner is not None:
                return Decision(
                    effect=effect,
                    reason=winner.reason or f"rule '{winner.id}' matched",
                    rule_id=winner.id,
                    source="policy",
                    trace=steps,
                )
        default = self.policy.defaults.effect
        return Decision(
            effect=default,
            reason=f"no rule matched; default is {default.value}",
            rule_id=None,
            source="default",
            trace=steps,
        )

    def approver_for(self, rule_id: str) -> str:
        """Return the approver string configured on a rule."""
        rule = self._by_id.get(rule_id)
        if rule is None:
            raise PolicyError(f"unknown rule '{rule_id}'", file=self.policy.source)
        return rule.approver

    def can_delegate(self, parent_role: str, child_role: str, depth: int) -> bool:
        """Say whether a role at this depth may delegate to a child role."""
        config = self.policy.agents.get(parent_role)
        if config is None or child_role not in config.can_delegate_to:
            return False
        limit = config.max_delegation_depth
        return limit is None or depth + 1 <= limit

    def _context(self, principal: Principal, call: ToolCall) -> dict[str, object]:
        now = self._clock.now() if self._needs_time else None
        calls = 0
        if self._needs_run and self._run_tool_calls is not None:
            calls = self._run_tool_calls(principal.run_id)
        return build_context(principal, call, run_tool_calls=calls, now=now)
