from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_castellan.delegation.chain import MAX_CHAIN_LENGTH, ChainVerifier
from agent_castellan.delegation.grants import chain_from_token, chain_to_token
from agent_castellan.errors import GrantError
from agent_castellan.models import Effect, Grant, Principal, ToolCall
from agent_castellan.testing.fakes import FrozenClock

KEY = bytes(range(32))
START = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass
class Env:
    clock: FrozenClock
    verifier: ChainVerifier
    root: Principal

    def child(self, parent: Principal, role: str = "worker") -> Principal:
        n = parent.depth + 1
        return Principal(
            agent_id=f"agent-{n}-{role}",
            role=role,
            run_id=parent.run_id,
            parent_id=parent.agent_id,
            parent_role=parent.role,
            depth=n,
        )

    def delegate(
        self,
        parent: Principal,
        chain: tuple[Grant, ...],
        *,
        tools: tuple[str, ...] = ("fs.*",),
        when: dict[str, Any] | None = None,
        ttl: int = 600,
        max_calls: int | None = None,
        role: str = "worker",
    ) -> tuple[Principal, tuple[Grant, ...]]:
        child = self.child(parent, role)
        grant = self.verifier.mint(parent, chain, child, tools, when, ttl, max_calls)
        return child, (*chain, grant)

    def allowed(self, chain: tuple[Grant, ...], who: Principal, tool: str = "fs.read") -> bool:
        decision = self.verifier.verify(chain, who, ToolCall(tool=tool, args={"path": "/work/a"}))
        assert decision.effect in (Effect.ALLOW, Effect.DENY)
        assert decision.source == "grant"
        return decision.effect is Effect.ALLOW


@pytest.fixture
def env() -> Env:
    clock = FrozenClock(START)
    root = Principal(agent_id="root", role="planner", run_id="run-1")
    return Env(clock, ChainVerifier(KEY, clock), root)


def test_valid_single_grant_allows_covered_tool(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    assert env.allowed(chain, child)
    assert not env.allowed(chain, child, "net.get")


def test_valid_five_deep_chain_passes(env: Env) -> None:
    who, chain = env.root, ()
    for level in range(5):
        who, chain = env.delegate(who, chain, tools=("fs.*",) if level < 4 else ("fs.read",))
    assert len(chain) == 5
    assert env.allowed(chain, who, "fs.read")
    assert not env.allowed(chain, who, "fs.write")


def test_chain_survives_token_round_trip(env: Env) -> None:
    who, chain = env.root, ()
    for _ in range(3):
        who, chain = env.delegate(who, chain)
    assert env.allowed(chain_from_token(chain_to_token(chain)), who)


def test_empty_chain_is_denied(env: Env) -> None:
    assert not env.allowed((), env.root)


@pytest.mark.parametrize(
    "change",
    [
        {"grant_id": "other"},
        {"issuer_agent_id": "mallory"},
        {"subject_agent_id": "mallory"},
        {"subject_role": "admin"},
        {"run_id": "run-2"},
        {"tools": ("**",)},
        {"when": {"args.path": {"eq": "/etc/passwd"}}},
        {"expires_at": START + timedelta(days=365)},
        {"max_calls": 999},
        {"signature": "00" * 32},
        {"signature": ""},
        {"signature": "é"},
    ],
)
@pytest.mark.parametrize("position", [0, 1, 2])
def test_tampering_any_field_of_any_grant_fails(
    env: Env, change: dict[str, Any], position: int
) -> None:
    who, chain = env.root, ()
    for _ in range(3):
        who, chain = env.delegate(who, chain, when={"args.path": {"glob": "/work/**"}}, max_calls=5)
    forged = chain[position].model_copy(update=change)
    tampered = (*chain[:position], forged, *chain[position + 1 :])
    assert env.allowed(chain, who)
    assert not env.allowed(tampered, who)


def test_dropping_a_grant_from_the_middle_fails(env: Env) -> None:
    who, chain = env.root, ()
    for _ in range(3):
        who, chain = env.delegate(who, chain)
    assert not env.allowed((chain[0], chain[2]), who)


def test_reordered_chain_fails(env: Env) -> None:
    who, chain = env.root, ()
    for _ in range(2):
        who, chain = env.delegate(who, chain)
    assert not env.allowed((chain[1], chain[0]), who)


def test_wrong_root_key_fails(env: Env) -> None:
    who, chain = env.delegate(env.root, ())
    other = ChainVerifier(bytes(reversed(range(32))), env.clock)
    decision = other.verify(chain, who, ToolCall(tool="fs.read"))
    assert decision.effect is Effect.DENY


def test_chain_for_other_principal_fails(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    impostor = child.model_copy(update={"agent_id": "someone-else"})
    wrong_role = child.model_copy(update={"role": "admin"})
    other_run = child.model_copy(update={"run_id": "run-9"})
    assert not env.allowed(chain, impostor)
    assert not env.allowed(chain, wrong_role)
    assert not env.allowed(chain, other_run)


def test_truncated_chain_does_not_grant_deeper_agent_access(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    grandchild, chain2 = env.delegate(child, chain, tools=("fs.read",))
    assert not env.allowed(chain, grandchild)
    assert env.allowed(chain2, grandchild)


def test_broken_link_fails(env: Env) -> None:
    _, chain = env.delegate(env.root, ())
    stranger = Principal(agent_id="stranger", role="x", run_id="run-1")
    other_child, other_chain = env.delegate(stranger, ())
    # Build a second grant honestly under `stranger`, then splice it after chain[0].
    spliced = (chain[0], other_chain[0])
    assert not env.allowed(spliced, other_child)


def test_chain_with_valid_signatures_but_widened_tools_is_rejected(env: Env) -> None:
    from agent_castellan.delegation.grants import sign, signature_key

    child, chain = env.delegate(env.root, (), tools=("fs.read",))
    grandchild = env.child(child)
    forged = Grant(
        grant_id="g-forged",
        issuer_agent_id=child.agent_id,
        subject_agent_id=grandchild.agent_id,
        subject_role=grandchild.role,
        run_id=child.run_id,
        tools=("**",),
        expires_at=chain[0].expires_at,
        signature="",
    )
    key = signature_key(chain[0], KEY)  # a holder of the last signature can sign a child
    forged = forged.model_copy(update={"signature": sign(key, forged)})
    assert not env.allowed((*chain, forged), grandchild, "fs.write")


def test_chain_with_valid_signatures_but_extended_expiry_or_calls_is_rejected(env: Env) -> None:
    from agent_castellan.delegation.grants import sign, signature_key

    child, chain = env.delegate(env.root, (), max_calls=2)
    grandchild = env.child(child)
    base = {
        "grant_id": "g-forged",
        "issuer_agent_id": child.agent_id,
        "subject_agent_id": grandchild.agent_id,
        "subject_role": grandchild.role,
        "run_id": child.run_id,
        "tools": ("fs.read",),
    }
    key = signature_key(chain[0], KEY)
    for extra in (
        {"expires_at": chain[0].expires_at + timedelta(seconds=1), "max_calls": 2},
        {"expires_at": chain[0].expires_at, "max_calls": 3},
        {"expires_at": chain[0].expires_at, "max_calls": None},
    ):
        forged = Grant(signature="", **base, **extra)  # type: ignore[arg-type]
        forged = forged.model_copy(update={"signature": sign(key, forged)})
        assert not env.allowed((*chain, forged), grandchild)


def test_expired_grant_fails(env: Env) -> None:
    child, chain = env.delegate(env.root, (), ttl=60)
    assert env.allowed(chain, child)
    env.clock.advance(59)
    assert env.allowed(chain, child)
    env.clock.advance(1)
    assert not env.allowed(chain, child)


def test_expired_ancestor_invalidates_the_chain(env: Env) -> None:
    child, chain = env.delegate(env.root, (), ttl=60)
    grandchild, chain2 = env.delegate(child, chain, ttl=30)
    env.clock.advance(45)
    assert not env.allowed(chain2, grandchild)


def test_when_conditions_of_all_ancestors_apply(env: Env) -> None:
    child, chain = env.delegate(env.root, (), when={"args.path": {"glob": "/work/**"}})
    grandchild, chain2 = env.delegate(child, chain, when={"args.mode": {"eq": "ro"}})
    verify = env.verifier.verify
    ok = ToolCall(tool="fs.read", args={"path": "/work/a", "mode": "ro"})
    assert verify(chain2, grandchild, ok).effect is Effect.ALLOW
    bad_path = ToolCall(tool="fs.read", args={"path": "/etc/a", "mode": "ro"})
    assert verify(chain2, grandchild, bad_path).effect is Effect.DENY
    bad_mode = ToolCall(tool="fs.read", args={"path": "/work/a", "mode": "rw"})
    assert verify(chain2, grandchild, bad_mode).effect is Effect.DENY
    missing = ToolCall(tool="fs.read", args={})
    assert verify(chain2, grandchild, missing).effect is Effect.DENY


def test_when_with_in_operator_and_agent_context(env: Env) -> None:
    child, chain = env.delegate(
        env.root,
        (),
        when={"all": [{"tool.name": {"in": ["fs.read"]}}, {"agent.role": {"eq": "worker"}}]},
    )
    assert env.allowed(chain, child, "fs.read")
    assert not env.allowed(chain, child, "fs.list")


def test_uncompilable_when_in_presented_grant_is_denied(env: Env) -> None:
    from agent_castellan.delegation.grants import sign

    child = env.child(env.root)
    grant = Grant(
        grant_id="g",
        issuer_agent_id="root",
        subject_agent_id=child.agent_id,
        subject_role=child.role,
        run_id=child.run_id,
        tools=("fs.*",),
        when={"args.path": {"bogus_op": 1}},
        expires_at=START + timedelta(hours=1),
        signature="",
    )
    grant = grant.model_copy(update={"signature": sign(KEY, grant)})
    assert not env.allowed((grant,), child)


def test_tool_name_case_is_normalised(env: Env) -> None:
    child, chain = env.delegate(env.root, (), tools=("FS.Read",))
    assert env.allowed(chain, child, "fs.READ")


def test_overlong_chain_is_denied(env: Env) -> None:
    who, chain = env.root, ()
    for _ in range(MAX_CHAIN_LENGTH + 1):
        who, chain = env.delegate(who, chain)
    assert not env.allowed(chain, who)


def test_naive_expiry_in_presented_grant_is_denied(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    naive = chain[0].model_copy(update={"expires_at": datetime(2031, 1, 1)})
    assert not env.allowed((naive,), child)


# ---- mint-time attenuation ----


def test_mint_rejects_widened_tools(env: Env) -> None:
    child, chain = env.delegate(env.root, (), tools=("fs.read",))
    for wider in (("fs.*",), ("fs.read", "net.get"), ("**",), ("*",)):
        with pytest.raises(GrantError):
            env.delegate(child, chain, tools=wider)


def test_mint_allows_narrower_tools(env: Env) -> None:
    child, chain = env.delegate(env.root, (), tools=("fs.*", "net.get"))
    _, chain2 = env.delegate(child, chain, tools=("fs.read", "net.get"))
    assert len(chain2) == 2


def test_mint_rejects_extended_expiry(env: Env) -> None:
    child, chain = env.delegate(env.root, (), ttl=60)
    with pytest.raises(GrantError):
        env.delegate(child, chain, ttl=61)
    env.delegate(child, chain, ttl=60)


def test_mint_rejects_widened_max_calls(env: Env) -> None:
    child, chain = env.delegate(env.root, (), max_calls=5)
    with pytest.raises(GrantError):
        env.delegate(child, chain, max_calls=6)
    with pytest.raises(GrantError):
        env.delegate(child, chain, max_calls=None)
    env.delegate(child, chain, max_calls=5)


def test_mint_allows_max_calls_when_parent_has_none(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    env.delegate(child, chain, max_calls=7)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tools": ()},
        {"tools": ("",)},
        {"tools": ("fs.?",)},
        {"ttl": 0},
        {"ttl": -5},
        {"max_calls": -1},
        {"when": {"args.x": {"nope": 1}}},
        {"when": {"x": {"eq": object()}}},
    ],
)
def test_mint_rejects_malformed_input(env: Env, kwargs: dict[str, Any]) -> None:
    with pytest.raises(GrantError):
        env.delegate(env.root, (), **kwargs)


def test_mint_rejects_delegation_by_agent_without_chain(env: Env) -> None:
    child = env.child(env.root)
    with pytest.raises(GrantError):
        env.verifier.mint(child, (), env.child(child), ("fs.read",), None, 60, None)


def test_mint_rejects_forged_or_foreign_parent_chain(env: Env) -> None:
    child, chain = env.delegate(env.root, ())
    forged = (chain[0].model_copy(update={"tools": ("**",)}),)
    with pytest.raises(GrantError):
        env.verifier.mint(child, forged, env.child(child), ("net.get",), None, 60, None)
    other = env.child(env.root, "other")
    with pytest.raises(GrantError):
        env.verifier.mint(other, chain, env.child(other), ("fs.read",), None, 60, None)
    garbled = (chain[0].model_copy(update={"signature": "é"}),)
    with pytest.raises(GrantError):
        env.verifier.mint(child, garbled, env.child(child), ("fs.read",), None, 60, None)


def test_mint_rejects_expired_parent_chain(env: Env) -> None:
    child, chain = env.delegate(env.root, (), ttl=10)
    env.clock.advance(10)
    with pytest.raises(GrantError):
        env.delegate(child, chain, ttl=5)


def test_mint_rejects_cross_run_or_wrong_parent(env: Env) -> None:
    child = env.child(env.root)
    other_run = child.model_copy(update={"run_id": "run-2"})
    with pytest.raises(GrantError):
        env.verifier.mint(env.root, (), other_run, ("fs.read",), None, 60, None)
    orphan = child.model_copy(update={"parent_id": "someone"})
    with pytest.raises(GrantError):
        env.verifier.mint(env.root, (), orphan, ("fs.read",), None, 60, None)


def test_minted_grant_fields(env: Env) -> None:
    child, chain = env.delegate(
        env.root, (), tools=("FS.*",), when={"args.p": {"eq": 1}}, max_calls=3
    )
    grant = chain[0]
    assert grant.issuer_agent_id == "root"
    assert grant.subject_agent_id == child.agent_id
    assert grant.subject_role == child.role
    assert grant.run_id == "run-1"
    assert grant.tools == ("fs.*",)
    assert grant.expires_at == START + timedelta(seconds=600)
    assert grant.max_calls == 3
    assert len(grant.signature) == 64
    assert grant.grant_id.startswith("grant-")


def test_grant_ids_are_unique(env: Env) -> None:
    ids = {env.delegate(env.root, ())[1][0].grant_id for _ in range(20)}
    assert len(ids) == 20
