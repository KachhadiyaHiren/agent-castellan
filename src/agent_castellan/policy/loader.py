"""YAML to Policy loader with line-numbered errors (WS1)."""

from __future__ import annotations

from pathlib import Path

from .schema import Policy


def load_policy(path: str | Path) -> Policy:
    """Load and validate a policy file."""
    raise NotImplementedError


def load_policy_text(text: str, *, source: str = "<string>") -> Policy:
    """Load and validate a policy from YAML text."""
    raise NotImplementedError
