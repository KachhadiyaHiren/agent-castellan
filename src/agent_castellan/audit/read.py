"""Reading and filtering audit log entries (WS4)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from pathlib import Path

from ..models import AuditEntry


def iter_entries(path: str | Path, run_id: str | None = None) -> Iterator[AuditEntry]:
    """Yield entries in file order, optionally only those of one run."""
    with Path(path).open("rb") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            entry = AuditEntry.model_validate_json(raw)
            if run_id is None or entry.principal.run_id == run_id:
                yield entry


def tail_entries(path: str | Path, n: int = 20, run_id: str | None = None) -> list[AuditEntry]:
    """Return the last `n` entries, optionally only those of one run."""
    if n <= 0:
        return []
    return list(deque(iter_entries(path, run_id), maxlen=n))
