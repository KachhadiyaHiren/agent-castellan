"""Grant minting, attenuation checks and token serialization (WS2)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cache, lru_cache
from typing import Any

from ..errors import GrantError
from ..models import Grant

_GRANT_FIELDS = frozenset(Grant.model_fields)
_SIGNED_FIELDS = _GRANT_FIELDS - {"signature"}
_FORBIDDEN_PATTERN_CHARS = re.compile(r"[\x00-\x20\x7f?\[\]{}\\]")

# Parent/child pattern tokens: a literal character, "S" (`*`) or "D" (`**`).
_Token = str


def normalize_pattern(pattern: str) -> str:
    """Lower-case a tool glob and reject empty or unsupported ones."""
    if not isinstance(pattern, str) or not pattern:
        raise GrantError("tool glob must be a non-empty string")
    lowered = pattern.lower()
    if _FORBIDDEN_PATTERN_CHARS.search(lowered):
        raise GrantError(f"tool glob '{pattern}' contains unsupported characters")
    return lowered


def _tokenize(pattern: str) -> list[_Token]:
    if pattern in ("*", "**"):
        return ["D"]  # a bare `*` matches every tool
    tokens: list[_Token] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            tokens.append("D")
            i += 2
        elif pattern[i] == "*":
            tokens.append("S")
            i += 1
        else:
            tokens.append(pattern[i])
            i += 1
    return tokens


def glob_subsumes(parent: str, child: str) -> bool:
    """Say whether every tool matched by `child` is matched by `parent` (reject when unsure)."""
    try:
        p = _tokenize(normalize_pattern(parent))
        c = _tokenize(normalize_pattern(child))
    except GrantError:
        return False

    @cache
    def covers(i: int, j: int) -> bool:
        if i == len(p):
            return j == len(c)
        sym = p[i]
        if sym == "D":
            return any(covers(i + 1, k) for k in range(j, len(c) + 1))
        if sym == "S":
            k = j
            while True:
                if covers(i + 1, k):
                    return True
                if k < len(c) and c[k] not in (".", "D"):
                    k += 1
                else:
                    return False
        return j < len(c) and c[j] == sym and covers(i + 1, j + 1)

    return covers(0, 0)


@lru_cache(maxsize=512)
def _tool_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    for sym in _tokenize(pattern):
        if sym == "D":
            out.append(".*")
        elif sym == "S":
            out.append("[^.]*")
        else:
            out.append(re.escape(sym))
    return re.compile("".join(out), re.DOTALL)


def tool_matches(pattern: str, tool: str) -> bool:
    """Say whether a tool glob matches a tool name (case-insensitive, never raises)."""
    try:
        return _tool_regex(normalize_pattern(pattern)).fullmatch(tool.lower()) is not None
    except GrantError:
        return False


def format_time(value: datetime) -> str:
    """Render a timezone-aware time in a fixed UTC form for signing."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise GrantError("grant times must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def canonical_bytes(grant: Grant) -> bytes:
    """Return the deterministic byte string that a grant's signature covers."""
    body: dict[str, Any] = {
        "grant_id": grant.grant_id,
        "issuer_agent_id": grant.issuer_agent_id,
        "subject_agent_id": grant.subject_agent_id,
        "subject_role": grant.subject_role,
        "run_id": grant.run_id,
        "tools": list(grant.tools),
        "when": grant.when,
        "expires_at": format_time(grant.expires_at),
        "max_calls": grant.max_calls,
    }
    try:
        return json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise GrantError(f"grant is not serializable: {exc}") from exc


def sign(key: bytes, grant: Grant) -> str:
    """Compute the hex HMAC of a grant under `key` (the root key or the previous signature)."""
    return hmac.new(key, canonical_bytes(grant), hashlib.sha256).hexdigest()


def signature_key(previous: Grant | None, root_key: bytes) -> bytes:
    """Return the HMAC key for the next grant: the root key, or the previous signature."""
    if previous is None:
        return root_key
    try:
        return bytes.fromhex(previous.signature)
    except ValueError as exc:
        raise GrantError("previous grant has a malformed signature") from exc


def attenuation_error(parent: Grant, child: Grant) -> str | None:
    """Return why `child` widens `parent`, or None when it only narrows."""
    for glob in child.tools:
        if not any(glob_subsumes(allowed, glob) for allowed in parent.tools):
            return f"tool '{glob}' is not covered by the parent grant's tools"
    try:
        if child.expires_at > parent.expires_at:
            return "expiry extends past the parent grant's expiry"
    except TypeError:
        return "grant times must be timezone-aware"
    if parent.max_calls is not None and (
        child.max_calls is None or child.max_calls > parent.max_calls
    ):
        return "max_calls exceeds the parent grant's max_calls"
    return None


def grant_to_token(grant: Grant) -> str:
    """Serialize a grant to a compact base64url JSON token."""
    body = json.loads(canonical_bytes(grant))
    body["signature"] = grant.signature
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def grant_from_token(token: str) -> Grant:
    """Parse a token produced by `grant_to_token`."""
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or set(data) != _GRANT_FIELDS:
            raise ValueError("unexpected fields")
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        data["tools"] = tuple(data["tools"])
        return Grant(**data)
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise GrantError(f"malformed grant token: {exc}") from exc


def chain_to_token(chain: Sequence[Grant]) -> str:
    """Serialize a chain as `token1.token2...`."""
    return ".".join(grant_to_token(grant) for grant in chain)


def chain_from_token(token: str) -> tuple[Grant, ...]:
    """Parse a chain produced by `chain_to_token`."""
    if not token:
        return ()
    return tuple(grant_from_token(part) for part in token.split("."))
