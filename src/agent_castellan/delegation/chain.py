"""ChainVerifier implementing interfaces.GrantVerifier (WS2)."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from ..errors import GrantError, PolicyError
from ..interfaces import Clock
from ..models import Decision, Effect, Grant, Principal, ToolCall
from ..policy.conditions import build_context, compile_condition
from .grants import (
    attenuation_error,
    normalize_pattern,
    sign,
    signature_key,
    tool_matches,
)

MAX_CHAIN_LENGTH = 32


def _deny(reason: str) -> Decision:
    return Decision(effect=Effect.DENY, reason=reason, source="grant")


class ChainVerifier:
    """Mints and verifies HMAC-chained delegation grants."""

    def __init__(self, key: bytes, clock: Clock) -> None:
        self._key = key
        self._clock = clock

    def verify(self, chain: Sequence[Grant], principal: Principal, call: ToolCall) -> Decision:
        """Check the whole grant chain against this call."""
        try:
            problem = self._chain_problem(chain)
            if problem is None:
                problem = self._principal_problem(chain, principal)
            if problem is None:
                problem = self._call_problem(chain, principal, call)
        except (GrantError, PolicyError, TypeError, ValueError, AttributeError) as exc:
            problem = f"grant chain could not be checked: {exc}"
        if problem is not None:
            return _deny(problem)
        return Decision(
            effect=Effect.ALLOW,
            reason=f"allowed by delegation chain of {len(chain)} grant(s)",
            source="grant",
        )

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
        self._check_parent(parent, parent_chain, child)
        if ttl_seconds <= 0:
            raise GrantError("ttl_seconds must be positive")
        if max_calls is not None and max_calls < 0:
            raise GrantError("max_calls must not be negative")
        patterns = tuple(normalize_pattern(tool) for tool in tools)
        if not patterns:
            raise GrantError("a grant must name at least one tool glob")
        if when is not None:
            try:
                compile_condition(when)
            except PolicyError as exc:
                raise GrantError(f"invalid 'when' condition: {exc}") from exc

        previous = parent_chain[-1] if parent_chain else None
        grant = Grant(
            grant_id=f"grant-{secrets.token_hex(8)}",
            issuer_agent_id=parent.agent_id,
            subject_agent_id=child.agent_id,
            subject_role=child.role,
            run_id=child.run_id,
            tools=patterns,
            when=when,
            expires_at=self._clock.now() + timedelta(seconds=ttl_seconds),
            max_calls=max_calls,
            signature="",
        )
        if previous is not None:
            problem = attenuation_error(previous, grant)
            if problem is not None:
                raise GrantError(f"delegation would widen the parent's power: {problem}")
        key = signature_key(previous, self._key)
        return grant.model_copy(update={"signature": sign(key, grant)})

    def _check_parent(
        self, parent: Principal, parent_chain: Sequence[Grant], child: Principal
    ) -> None:
        if parent_chain:
            try:
                problem = self._chain_problem(parent_chain) or self._expiry_problem(parent_chain)
                if problem is None:
                    problem = self._principal_problem(parent_chain, parent)
            except (TypeError, ValueError) as exc:
                problem = f"malformed grant: {exc}"
            if problem is not None:
                raise GrantError(f"parent chain is not valid: {problem}")
        elif parent.depth != 0:
            raise GrantError(f"delegated agent '{parent.agent_id}' has no grant chain to extend")
        if child.run_id != parent.run_id:
            raise GrantError("child and parent must belong to the same run")
        if child.parent_id != parent.agent_id:
            raise GrantError("child principal is not a child of the delegating parent")

    def _chain_problem(self, chain: Sequence[Grant]) -> str | None:
        """Check signatures, links and attenuation; return a reason or None."""
        if not chain:
            return "no grant chain presented"
        if len(chain) > MAX_CHAIN_LENGTH:
            return f"grant chain is longer than {MAX_CHAIN_LENGTH}"
        previous: Grant | None = None
        for index, grant in enumerate(chain):
            expected = sign(signature_key(previous, self._key), grant)
            if not hmac.compare_digest(expected.encode(), grant.signature.encode()):
                return f"signature of grant {index} ({grant.grant_id}) is invalid"
            if previous is not None:
                problem = self._link_problem(previous, grant, index)
                if problem is not None:
                    return problem
            previous = grant
        return None

    @staticmethod
    def _link_problem(previous: Grant, grant: Grant, index: int) -> str | None:
        if grant.issuer_agent_id != previous.subject_agent_id:
            return f"grant {index} is not issued by the subject of grant {index - 1}"
        if grant.run_id != previous.run_id:
            return f"grant {index} belongs to a different run"
        problem = attenuation_error(previous, grant)
        if problem is not None:
            return f"grant {index} widens its parent: {problem}"
        return None

    def _expiry_problem(self, chain: Sequence[Grant]) -> str | None:
        now = self._clock.now()
        for index, grant in enumerate(chain):
            if now >= grant.expires_at:
                return f"grant {index} ({grant.grant_id}) has expired"
        return None

    @staticmethod
    def _principal_problem(chain: Sequence[Grant], principal: Principal) -> str | None:
        last = chain[-1]
        if last.subject_agent_id != principal.agent_id:
            return "last grant was not issued to this agent"
        if last.subject_role != principal.role:
            return "last grant was issued to a different role"
        if any(grant.run_id != principal.run_id for grant in chain):
            return "grant chain belongs to a different run"
        return None

    def _call_problem(
        self, chain: Sequence[Grant], principal: Principal, call: ToolCall
    ) -> str | None:
        problem = self._expiry_problem(chain)
        if problem is not None:
            return problem
        context = build_context(principal, call, now=self._clock.now())
        for index, grant in enumerate(chain):
            problem = self._grant_problem(grant, index, call, context)
            if problem is not None:
                return problem
        return None

    @staticmethod
    def _grant_problem(
        grant: Grant, index: int, call: ToolCall, context: Mapping[str, Any]
    ) -> str | None:
        if not any(tool_matches(pattern, call.tool) for pattern in grant.tools):
            return f"tool '{call.tool}' is not covered by grant {index} ({grant.grant_id})"
        if grant.when is not None and not compile_condition(grant.when)(context):
            return f"condition of grant {index} ({grant.grant_id}) is not met"
        return None
