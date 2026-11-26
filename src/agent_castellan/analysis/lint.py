"""Policy lint checks L001-L007 (WS4)."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from ..models import Effect
from ..policy.schema import Policy, Rule


@dataclass(frozen=True)
class Finding:
    """One lint finding."""

    check_id: str  # L001 .. L007
    severity: str  # error | warning
    message: str
    rule_id: str | None = None
    line: int | None = None


_WILDCARD_ALL = {"*", "**"}


def _has_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a tool glob: `*` stops at `.`, `**` crosses it, bare `*` matches everything."""
    if pattern in _WILDCARD_ALL:
        return re.compile(".*", re.DOTALL)
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^.]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^.]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def tool_pattern_covers(outer: str, inner: str) -> bool:
    """Conservatively say whether every tool matched by `inner` is matched by `outer`."""
    outer, inner = outer.lower(), inner.lower()
    if outer == inner or outer in _WILDCARD_ALL:
        return True
    if not _has_wildcard(inner):
        return _glob_regex(outer).fullmatch(inner) is not None
    if outer.endswith(".**"):
        return inner.startswith(outer[:-2]) and "**" not in outer[:-3]
    if outer.endswith(".*") and "*" not in outer[:-2] and "?" not in outer[:-2]:
        rest = inner[len(outer) - 1 :] if inner.startswith(outer[:-1]) else None
        return rest is not None and "." not in rest and "**" not in rest
    return False


def tools_covered(outer: Sequence[str], inner: Sequence[str]) -> bool:
    """Say whether every pattern in `inner` is covered by some pattern in `outer`."""
    return all(any(tool_pattern_covers(o, i) for o in outer) for i in inner)


def agents_covered(outer: Collection[str], inner: Collection[str]) -> bool:
    """Say whether every role selected by `inner` is also selected by `outer`."""
    if not outer or "*" in outer:
        return True
    if not inner or "*" in inner:
        return False
    return set(inner) <= set(outer)


def reachable_roles(delegations: Mapping[str, Sequence[str]]) -> set[str]:
    """Roles that can exist in a run: roots (delegators never delegated to) and descendants."""
    targets = {t for ts in delegations.values() for t in ts}
    roots = {role for role, ts in delegations.items() if ts and role not in targets}
    seen = set(roots)
    stack = list(roots)
    while stack:
        for child in delegations.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _approver_role(rule: Rule) -> str | None:
    return rule.approver[5:] if rule.approver.startswith("role:") else None


def _check_shadowed(policy: Policy) -> list[Finding]:
    found: list[Finding] = []
    denies = [r for r in policy.rules if r.effect is Effect.DENY and not r.when]
    for rule in policy.rules:
        if rule.effect is not Effect.ALLOW:
            continue
        for deny in denies:
            if tools_covered(deny.tools, rule.tools) and agents_covered(deny.agents, rule.agents):
                found.append(
                    Finding(
                        "L001",
                        "warning",
                        f"allow rule '{rule.id}' is shadowed by unconditional deny rule "
                        f"'{deny.id}' and can never take effect",
                        rule.id,
                        rule.line,
                    )
                )
                break
    return found


def _check_duplicates(policy: Policy) -> list[Finding]:
    seen: set[str] = set()
    found: list[Finding] = []
    for rule in policy.rules:
        if rule.id in seen:
            found.append(
                Finding("L002", "error", f"duplicate rule id '{rule.id}'", rule.id, rule.line)
            )
        seen.add(rule.id)
    return found


def _check_wildcard_allow(policy: Policy) -> list[Finding]:
    return [
        Finding(
            "L003",
            "warning",
            f"rule '{r.id}' allows every tool with no conditions",
            r.id,
            r.line,
        )
        for r in policy.rules
        if r.effect is Effect.ALLOW and not r.when and any(t in _WILDCARD_ALL for t in r.tools)
    ]


def _check_undefined_roles(policy: Policy) -> list[Finding]:
    defined = set(policy.agents)
    found: list[Finding] = []
    for rule in policy.rules:
        refs = [(a, "agents") for a in rule.agents if a != "*" and not _has_wildcard(a)]
        approver = _approver_role(rule)
        if approver is not None:
            refs.append((approver, "approver"))
        for role, where in refs:
            if role not in defined:
                found.append(
                    Finding(
                        "L004",
                        "error",
                        f"rule '{rule.id}' references role '{role}' in {where} "
                        "which is not defined in 'agents'",
                        rule.id,
                        rule.line,
                    )
                )
    for role, cfg in policy.agents.items():
        for target in cfg.can_delegate_to:
            if target not in defined:
                found.append(
                    Finding(
                        "L004",
                        "error",
                        f"role '{role}' can_delegate_to undefined role '{target}'",
                    )
                )
    return found


def _check_approver_exists(
    policy: Policy, delegations: Mapping[str, Sequence[str]]
) -> list[Finding]:
    if not any(delegations.values()):
        return []
    live = reachable_roles(delegations)
    return [
        Finding(
            "L005",
            "warning",
            f"ask rule '{r.id}' needs approver role '{role}' which can never exist in a run",
            r.id,
            r.line,
        )
        for r in policy.rules
        if r.effect is Effect.ASK
        and (role := _approver_role(r)) is not None
        and role in policy.agents
        and role not in live
    ]


def _check_unreachable(policy: Policy, delegations: Mapping[str, Sequence[str]]) -> list[Finding]:
    if not any(delegations.values()):
        return []
    live = reachable_roles(delegations)
    return [
        Finding(
            "L006",
            "warning",
            f"role '{role}' is not reachable from any can_delegate_to chain",
        )
        for role in policy.agents
        if role not in live
    ]


def lint_policy(policy: Policy) -> list[Finding]:
    """Run every lint check against a policy."""
    delegations = {role: cfg.can_delegate_to for role, cfg in policy.agents.items()}
    findings = [
        *_check_shadowed(policy),
        *_check_duplicates(policy),
        *_check_wildcard_allow(policy),
        *_check_undefined_roles(policy),
        *_check_approver_exists(policy, delegations),
        *_check_unreachable(policy, delegations),
    ]
    if policy.defaults.effect is Effect.ALLOW:
        findings.append(
            Finding("L007", "warning", "defaults.effect is 'allow': unmatched calls are permitted")
        )
    return findings
