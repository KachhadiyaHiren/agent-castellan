"""Hash-chained JSONL audit writer implementing interfaces.AuditSink (WS4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..interfaces import Clock
from ..models import AuditEntry, Decision, Principal, ToolCall
from ._chain import GENESIS_HASH, canonical, entry_hash

try:  # POSIX only; on other platforms writers in one process still serialise via the OS append.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

__all__ = ["GENESIS_HASH", "AuditLog"]

_CHUNK = 4096


def _last_line(fd: int) -> bytes | None:
    """Return the last non-empty line of an open file, reading backwards."""
    size = os.lseek(fd, 0, os.SEEK_END)
    data = b""
    pos = size
    while pos > 0:
        step = min(_CHUNK, pos)
        pos -= step
        os.lseek(fd, pos, os.SEEK_SET)
        data = os.read(fd, step) + data
        stripped = data.rstrip(b"\n")
        if b"\n" in stripped:
            return stripped.rsplit(b"\n", 1)[1]
    stripped = data.rstrip(b"\n")
    return stripped or None


class AuditLog:
    """Append-only, tamper-evident decision log in JSON Lines format.

    Each entry stores the hash of the previous one, so editing or removing an entry in the
    middle of the file is detected by `verify_log`. Writers take an exclusive file lock,
    so several processes can append to one log.

    Args:
        path: Log file; created (with parent directories) on the first append.
        clock: Time source for the `at` field.
        fsync: Flush every entry to disk before returning. Turn off for speed in tests.
    """

    def __init__(self, path: str | Path, clock: Clock, *, fsync: bool = True) -> None:
        self._path = Path(path)
        self._clock = clock
        self._fsync = fsync

    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry:
        """Record one decision and return the stored entry.

        Args:
            principal: The agent that made the call.
            call: The call that was decided.
            decision: The decision reached.

        Returns:
            The entry as written, including its `seq`, `prev_hash` and `hash`.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                seq, prev = self._tail_state(fd)
                body: dict[str, Any] = {
                    "seq": seq,
                    "at": self._clock.now(),
                    "principal": principal,
                    "call": call,
                    "decision": decision,
                    "prev_hash": prev,
                }
                dumped = AuditEntry.model_construct(**body, hash="").model_dump(
                    mode="json", exclude={"hash"}
                )
                digest = entry_hash(prev, dumped)
                dumped["hash"] = digest
                os.write(fd, (canonical(dumped) + "\n").encode())
                if self._fsync:
                    os.fsync(fd)
            finally:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        return AuditEntry.model_validate(dumped)

    @staticmethod
    def _tail_state(fd: int) -> tuple[int, str]:
        """Return the next seq and previous hash from the last stored line."""
        last = _last_line(fd)
        if last is None:
            return 0, GENESIS_HASH
        record = json.loads(last)
        return int(record["seq"]) + 1, str(record["hash"])
