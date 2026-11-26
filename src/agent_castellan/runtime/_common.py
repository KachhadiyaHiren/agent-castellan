"""Helpers shared by the approval and budget backends."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..models import ToolCall

_BUSY_TIMEOUT_SECONDS = 30.0


def call_hash(call: ToolCall) -> str:
    """Return the SHA-256 of the canonical JSON of `{tool, args}`."""
    payload = json.dumps(
        {"tool": call.tool, "args": call.args},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def init_sqlite(path: Path, schema: str) -> None:
    """Create parent folders, enable WAL and apply a schema (idempotent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(schema)
    finally:
        conn.close()


@contextmanager
def immediate_transaction(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection and run the body inside a `BEGIN IMMEDIATE` transaction."""
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()
