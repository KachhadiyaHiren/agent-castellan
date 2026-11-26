from __future__ import annotations

import pytest

from agent_castellan.delegation.keys import KEY_ENV, load_root_key
from agent_castellan.errors import GrantError


def test_explicit_key_wins_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "ab" * 32)
    assert load_root_key(b"k" * 32) == b"k" * 32


def test_key_from_environment_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "ab" * 32)
    assert load_root_key() == bytes.fromhex("ab" * 32)


@pytest.mark.parametrize("value", ["zz", "ab" * 8])
def test_bad_environment_key_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(KEY_ENV, value)
    with pytest.raises(GrantError):
        load_root_key()


def test_short_explicit_key_is_rejected() -> None:
    with pytest.raises(GrantError):
        load_root_key(b"short")


def test_generated_key_warns_and_is_random(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.warns(RuntimeWarning):
        first = load_root_key()
    with pytest.warns(RuntimeWarning):
        second = load_root_key()
    assert len(first) == 32
    assert first != second
