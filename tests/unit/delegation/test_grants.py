from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from agent_castellan.delegation.grants import (
    canonical_bytes,
    chain_from_token,
    chain_to_token,
    format_time,
    glob_subsumes,
    grant_from_token,
    grant_to_token,
    tool_matches,
)
from agent_castellan.errors import GrantError
from agent_castellan.models import Grant


@pytest.mark.parametrize(
    ("parent", "child"),
    [
        ("*", "fs.write"),
        ("*", "*"),
        ("**", "fs.*"),
        ("fs.*", "fs.write"),
        ("fs.*", "fs.*"),
        ("fs.*", "fs.re*"),
        ("fs.write", "fs.write"),
        ("FS.write", "fs.WRITE"),
        ("**", "mcp:fs/read_file"),
        ("mcp:**", "mcp:fs/read_file"),
        ("mcp:*", "mcp:fs/read_file"),
        ("fs.**", "fs.a.b"),
        ("fs.**", "fs.*.b"),
        ("fs.**", "fs.**"),
        ("a*b", "a*xb"),
        ("*.read", "fs.read"),
        ("**.read", "fs.sub.read"),
    ],
)
def test_glob_subsumes_accepts_narrower_patterns(parent: str, child: str) -> None:
    assert glob_subsumes(parent, child)


@pytest.mark.parametrize(
    ("parent", "child"),
    [
        ("fs.write", "fs.*"),
        ("fs.write", "*"),
        ("fs.*", "*"),
        ("fs.*", "**"),
        ("fs.*", "fs.**"),
        ("fs.*", "fs.a.b"),
        ("fs.*", "fs.*.b"),
        ("fs.*", "net.get"),
        ("fs.write", "fs.writex"),
        ("fs.write", "fs.writ"),
        ("*.read", "fs.sub.read"),
        ("*.read", "**"),
        ("a*b", "a*"),
        ("", "fs.write"),
        ("fs.*", ""),
        ("fs.?", "fs.a"),
        ("fs.[a]", "fs.a"),
        ("fs.*", "fs. x"),
        ("fs.*", "fs.\x00"),
    ],
)
def test_glob_subsumes_rejects_wider_or_unsure_patterns(parent: str, child: str) -> None:
    assert not glob_subsumes(parent, child)


@pytest.mark.parametrize(
    ("pattern", "tool", "expected"),
    [
        ("*", "anything.at.all", True),
        ("fs.*", "fs.write", True),
        ("fs.*", "fs.a.b", False),
        ("fs.**", "fs.a.b", True),
        ("FS.*", "Fs.Write", True),
        ("fs.write", "fs.write2", False),
        ("fs.?", "fs.a", False),
        ("", "fs.a", False),
    ],
)
def test_tool_matches(pattern: str, tool: str, expected: bool) -> None:
    assert tool_matches(pattern, tool) is expected


def make_grant(**overrides: object) -> Grant:
    fields: dict[str, object] = {
        "grant_id": "g1",
        "issuer_agent_id": "a",
        "subject_agent_id": "b",
        "subject_role": "coder",
        "run_id": "r1",
        "tools": ("fs.*",),
        "when": {"args.path": {"glob": "/work/**"}},
        "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
        "max_calls": 3,
        "signature": "ab" * 32,
    }
    fields.update(overrides)
    return Grant(**fields)  # type: ignore[arg-type]


def test_token_round_trip_preserves_grant() -> None:
    grant = make_grant()
    assert grant_from_token(grant_to_token(grant)) == grant


def test_chain_token_round_trip() -> None:
    chain = (make_grant(grant_id="g1"), make_grant(grant_id="g2"))
    assert chain_from_token(chain_to_token(chain)) == chain
    assert chain_from_token(chain_to_token(())) == ()


def test_canonical_bytes_ignore_signature_but_cover_every_other_field() -> None:
    base = make_grant()
    assert canonical_bytes(base) == canonical_bytes(make_grant(signature="00" * 32))
    variants = [
        {"grant_id": "x"},
        {"issuer_agent_id": "x"},
        {"subject_agent_id": "x"},
        {"subject_role": "x"},
        {"run_id": "x"},
        {"tools": ("fs.**",)},
        {"when": None},
        {"expires_at": datetime(2031, 1, 1, tzinfo=UTC)},
        {"max_calls": 4},
    ]
    for change in variants:
        assert canonical_bytes(make_grant(**change)) != canonical_bytes(base), change


@pytest.mark.parametrize(
    "token",
    ["", "!!!", "e30", base64.urlsafe_b64encode(b"[1]").decode(), "a.b"],
)
def test_malformed_tokens_raise_grant_error(token: str) -> None:
    with pytest.raises(GrantError):
        grant_from_token(token)


def test_token_with_extra_or_missing_fields_is_rejected() -> None:
    data = json.loads(canonical_bytes(make_grant()))
    data["signature"] = "ab"
    good = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    grant_from_token(good)
    data["extra"] = 1
    with pytest.raises(GrantError):
        grant_from_token(base64.urlsafe_b64encode(json.dumps(data).encode()).decode())
    del data["extra"], data["tools"]
    with pytest.raises(GrantError):
        grant_from_token(base64.urlsafe_b64encode(json.dumps(data).encode()).decode())


def test_naive_times_are_rejected() -> None:
    with pytest.raises(GrantError):
        format_time(datetime(2030, 1, 1))


def test_unserializable_when_is_rejected() -> None:
    with pytest.raises(GrantError):
        canonical_bytes(make_grant(when={"x": {"eq": object()}}))
