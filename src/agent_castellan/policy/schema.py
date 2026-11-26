"""Pydantic models for the policy YAML document (WS1 owns; Phase 0 provides the shape)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import Effect


class Defaults(BaseModel):
    """Fallback behaviour when no rule matches."""

    model_config = ConfigDict(frozen=True)
    effect: Effect = Effect.DENY


class AgentConfig(BaseModel):
    """Per-role delegation settings."""

    model_config = ConfigDict(frozen=True)
    can_delegate_to: tuple[str, ...] = ()
    max_delegation_depth: int | None = None


class Rule(BaseModel):
    """One allow, deny or ask rule."""

    model_config = ConfigDict(frozen=True)
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


class RunBudget(BaseModel):
    """Limits shared across a whole run tree."""

    model_config = ConfigDict(frozen=True)
    max_tool_calls: int | None = None
    max_cost_units: float | None = None


class RoleBudget(BaseModel):
    """Limits applied per agent role."""

    model_config = ConfigDict(frozen=True)
    max_tool_calls: int | None = None
    max_cost_units: float | None = None


class BudgetsConfig(BaseModel):
    """The `budgets` section of a policy."""

    model_config = ConfigDict(frozen=True)
    run: RunBudget = Field(default_factory=RunBudget)
    per_role: dict[str, RoleBudget] = Field(default_factory=dict)


class ApprovalsConfig(BaseModel):
    """The `approvals` section of a policy."""

    model_config = ConfigDict(frozen=True)
    ttl_seconds: int = 600


class AuditConfig(BaseModel):
    """The `audit` section of a policy."""

    model_config = ConfigDict(frozen=True)
    path: str = "./castellan-audit.jsonl"


class Policy(BaseModel):
    """A loaded, validated policy."""

    model_config = ConfigDict(frozen=True)
    version: int = 1
    defaults: Defaults = Field(default_factory=Defaults)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    rules: tuple[Rule, ...] = ()
    budgets: BudgetsConfig = Field(default_factory=BudgetsConfig)
    approvals: ApprovalsConfig = Field(default_factory=ApprovalsConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    source: str | None = None
