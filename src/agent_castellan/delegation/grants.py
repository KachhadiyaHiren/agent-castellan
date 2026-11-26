"""Grant minting, attenuation checks and token serialization (WS2)."""

from __future__ import annotations

from ..models import Grant


def glob_subsumes(parent: str, child: str) -> bool:
    """Say whether every tool matched by `child` is matched by `parent` (reject when unsure)."""
    raise NotImplementedError


def grant_to_token(grant: Grant) -> str:
    """Serialize a grant to a compact base64url JSON token."""
    raise NotImplementedError


def grant_from_token(token: str) -> Grant:
    """Parse a token produced by `grant_to_token`."""
    raise NotImplementedError


def chain_to_token(chain: tuple[Grant, ...]) -> str:
    """Serialize a chain as `token1.token2...`."""
    raise NotImplementedError


def chain_from_token(token: str) -> tuple[Grant, ...]:
    """Parse a chain produced by `chain_to_token`."""
    raise NotImplementedError
