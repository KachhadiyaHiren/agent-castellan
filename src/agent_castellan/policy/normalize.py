"""Call normalization, run before any matching (WS1; see PLAN.md §4.6)."""

from __future__ import annotations

from ..models import ToolCall


def normalize_call(call: ToolCall) -> ToolCall:
    """Return the canonical form of a call, or raise PolicyError if it is invalid."""
    raise NotImplementedError


def call_hash(call: ToolCall) -> str:
    """Return the SHA-256 hex digest of the canonical `{tool, args}` JSON."""
    raise NotImplementedError
