"""ChainVerifier implementing interfaces.GrantVerifier (WS2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..interfaces import Clock
from ..models import Decision, Grant, Principal, ToolCall


class ChainVerifier:
    """Mints and verifies HMAC-chained delegation grants."""

    def __init__(self, key: bytes, clock: Clock) -> None:
        self._key = key
        self._clock = clock

    def verify(self, chain: Sequence[Grant], principal: Principal, call: ToolCall) -> Decision:
        """Check the whole grant chain against this call."""
        raise NotImplementedError

    def mint(
        self,
        parent: Principal,
        parent_chain: Sequence[Grant],
        child: Principal,
        tools: Sequence[str],
        when: dict[str, Any] | None,
        ttl_seconds: int,
        max_calls: int | None,
    ) -> Grant:
        """Create a grant that can only narrow the parent's power."""
        raise NotImplementedError
