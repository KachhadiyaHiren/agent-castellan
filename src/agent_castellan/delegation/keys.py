"""Root key management (WS2)."""

from __future__ import annotations


def load_root_key(key: bytes | None = None) -> bytes:
    """Return the root key from the argument, `CASTELLAN_KEY` (hex) or a fresh random key."""
    raise NotImplementedError
