"""Pydantic models for the policy YAML document (WS1 owns; Phase 0 provides the shape)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import Effect

APPROVER_RE = re.compile(r"human|role:\S+|agent:\S+")


class Defaults(BaseModel):
    """Fallback behaviour when no rule matches."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    effect: Effect = Effect.DENY


class AgentConfig(BaseModel):
    """Per-role delegation settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    can_delegate_to: tuple[str, ...] = ()
    max_delegation_depth: int | None = Field(default=None, ge=0)
    line: int | None = None


class Rule(BaseModel):
    """One allow, deny or ask rule.

    Attributes:
        id: Unique name, shown in decisions, traces and audit entries.
        description: Free-text note for humans.
        agents: Roles the rule applies to; `("*",)` means all.
        tools: Tool globs the rule applies to.
        when: Optional condition tree; see the policy language reference.
        effect: `allow`, `deny` or `ask`.
        reason: Message returned in the decision.
        approver: For `ask` rules: `human`, `role:<role>` or `agent:<id>`.
        priority: Tie-breaker between matching rules of the same effect; higher wins.
        line: Line in the source file, filled in by the loader.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    description: str | None = None
    agents: tuple[str, ...] = ("*",)
    tools: tuple[str, ...] = ("*",)
    when: dict[str, Any] | None = None
    effect: Effect
    reason: str | None = None
    approver: str = "human"
    priority: int = 0
    line: int | None = None

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule id must not be blank")
        return value

    @field_validator("agents", "tools")
    @classmethod
    def _non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("must be a non-empty list of non-empty strings")
        return value

    @field_validator("approver")
    @classmethod
    def _approver_form(cls, value: str) -> str:
        if not APPROVER_RE.fullmatch(value):
            raise ValueError("approver must be 'human', 'role:<role>' or 'agent:<id>'")
        return value


class RunBudget(BaseModel):
    """Limits shared across a whole run tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_cost_units: float | None = Field(default=None, ge=0)


class RoleBudget(BaseModel):
    """Limits applied per agent role."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_cost_units: float | None = Field(default=None, ge=0)


class BudgetsConfig(BaseModel):
    """The `budgets` section of a policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run: RunBudget = Field(default_factory=RunBudget)
    per_role: dict[str, RoleBudget] = Field(default_factory=dict)


class ApprovalsConfig(BaseModel):
    """The `approvals` section of a policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    ttl_seconds: int = Field(default=600, gt=0)


class AuditConfig(BaseModel):
    """The `audit` section of a policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str = "./castellan-audit.jsonl"


class Policy(BaseModel):
    """A loaded, validated policy: the typed form of a policy YAML document.

    Attributes:
        version: Policy language version; always 1.
        defaults: What happens when no rule matches.
        agents: Role definitions, keyed by role name.
        rules: Rules in file order.
        budgets: Run and per-role limits.
        approvals: Approval settings.
        audit: Audit log settings.
        source: File the policy was loaded from, if any.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal[1] = 1
    defaults: Defaults = Field(default_factory=Defaults)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    rules: tuple[Rule, ...] = ()
    budgets: BudgetsConfig = Field(default_factory=BudgetsConfig)
    approvals: ApprovalsConfig = Field(default_factory=ApprovalsConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    source: str | None = None

    @field_validator("agents", mode="before")
    @classmethod
    def _null_roles_are_empty(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {role: ({} if cfg is None else cfg) for role, cfg in value.items()}
        return value
