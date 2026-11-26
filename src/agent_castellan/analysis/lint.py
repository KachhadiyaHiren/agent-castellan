"""Policy lint checks L001-L007 (WS4)."""

from __future__ import annotations

from dataclasses import dataclass

from ..policy.schema import Policy


@dataclass(frozen=True)
class Finding:
    """One lint finding."""

    check_id: str  # L001 .. L007
    severity: str  # error | warning
    message: str
    rule_id: str | None = None
    line: int | None = None


def lint_policy(policy: Policy) -> list[Finding]:
    """Run every lint check against a policy."""
    raise NotImplementedError
