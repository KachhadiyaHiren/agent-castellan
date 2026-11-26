"""Canonical serialisation and hashing shared by the audit writer and verifier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

GENESIS_HASH = "0" * 64


def canonical(data: Mapping[str, Any]) -> str:
    """Serialise a mapping to canonical JSON (sorted keys, no spaces)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(prev_hash: str, entry: Mapping[str, Any]) -> str:
    """Hash an entry (any `hash` key is ignored) chained onto the previous hash."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256((prev_hash + canonical(body)).encode()).hexdigest()
