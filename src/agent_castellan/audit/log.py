"""Hash-chained JSONL audit writer implementing interfaces.AuditSink (WS4)."""

from __future__ import annotations

from pathlib import Path

from ..interfaces import Clock
from ..models import AuditEntry, Decision, Principal, ToolCall

GENESIS_HASH = "0" * 64


class AuditLog:
    """Append-only, tamper-evident decision log."""

    def __init__(self, path: str | Path, clock: Clock, *, fsync: bool = True) -> None:
        self._path = Path(path)
        self._clock = clock
        self._fsync = fsync

    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry:
        """Record one decision and return the stored entry."""
        raise NotImplementedError
