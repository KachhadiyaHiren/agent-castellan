"""Root key management (WS2)."""

from __future__ import annotations

import os
import secrets
import warnings

from ..errors import GrantError

KEY_ENV = "CASTELLAN_KEY"
MIN_KEY_BYTES = 32


def load_root_key(key: bytes | None = None) -> bytes:
    """Return the root key from the argument, `CASTELLAN_KEY` (hex) or a fresh random key."""
    if key is not None:
        return _checked(key, "key argument")
    env = os.environ.get(KEY_ENV)
    if env:
        try:
            decoded = bytes.fromhex(env.strip())
        except ValueError as exc:
            raise GrantError(f"{KEY_ENV} must be hex-encoded") from exc
        return _checked(decoded, KEY_ENV)
    warnings.warn(
        f"no root key given and {KEY_ENV} is unset; generated a random key for this process, "
        "so grants will not verify in other processes",
        RuntimeWarning,
        stacklevel=2,
    )
    return secrets.token_bytes(MIN_KEY_BYTES)


def _checked(key: bytes, source: str) -> bytes:
    if len(key) < MIN_KEY_BYTES:
        raise GrantError(f"root key from {source} must be at least {MIN_KEY_BYTES} bytes")
    return bytes(key)
