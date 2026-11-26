"""Audit log chain verification (WS4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of verifying a log: `bad_seq` and `reason` are set when `ok` is False."""

    ok: bool
    entries: int
    bad_seq: int | None = None
    reason: str | None = None  # hash_mismatch | gap | reordered


def verify_log(path: str | Path) -> VerifyResult:
    """Verify the hash chain of an audit log file."""
    raise NotImplementedError
