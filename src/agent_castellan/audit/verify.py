"""Audit log chain verification (WS4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._chain import GENESIS_HASH, canonical, entry_hash


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of verifying a log: `bad_seq` and `reason` are set when `ok` is False."""

    ok: bool
    entries: int
    bad_seq: int | None = None
    reason: str | None = None  # hash_mismatch | gap | reordered


def _parse(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def verify_log(path: str | Path) -> VerifyResult:
    """Verify the hash chain of an audit log file."""
    text = Path(path).read_bytes()
    lines = [ln for ln in text.split(b"\n") if ln.strip()]
    parsed = [_parse(ln) for ln in lines]
    seqs = {p["seq"] for p in parsed if p is not None and isinstance(p.get("seq"), int)}
    prev = GENESIS_HASH
    for index, (raw, rec) in enumerate(zip(lines, parsed, strict=True)):
        if rec is None or not isinstance(rec.get("seq"), int):
            return VerifyResult(False, index, index, "hash_mismatch")
        seq = rec["seq"]
        if seq != index:
            reason = "reordered" if index in seqs or seq < index else "gap"
            return VerifyResult(False, index, seq, reason)
        ok = (
            rec.get("prev_hash") == prev
            and isinstance(rec.get("hash"), str)
            and rec["hash"] == entry_hash(prev, rec)
            and raw.decode("utf-8", "replace") == canonical(rec)
        )
        if not ok:
            return VerifyResult(False, index, seq, "hash_mismatch")
        prev = rec["hash"]
    return VerifyResult(True, len(lines))
