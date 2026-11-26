"""Castellan: least-privilege permissions for multi-agent AI systems."""

from __future__ import annotations

from .errors import (
    ApprovalRequired,
    BudgetExceeded,
    CastellanError,
    GrantError,
    PermissionDenied,
    PolicyError,
)
from .guard import Guard
from .models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEntry,
    Decision,
    Effect,
    Grant,
    Principal,
    ToolCall,
    TraceStep,
)

__version__ = "0.0.1"

__all__ = [
    "ApprovalRequest",
    "ApprovalRequired",
    "ApprovalStatus",
    "AuditEntry",
    "BudgetExceeded",
    "CastellanError",
    "Decision",
    "Effect",
    "Grant",
    "GrantError",
    "Guard",
    "PermissionDenied",
    "PolicyError",
    "Principal",
    "ToolCall",
    "TraceStep",
    "__version__",
]
