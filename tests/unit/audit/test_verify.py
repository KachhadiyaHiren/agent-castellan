from __future__ import annotations

from pathlib import Path

import pytest

from agent_castellan.audit import AuditLog, verify_log
from agent_castellan.models import Decision, Effect, Principal, ToolCall
from agent_castellan.testing.fakes import FrozenClock


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, FrozenClock(), fsync=False)
    for i in range(5):
        log.append(
            Principal(agent_id="a", role="r", run_id="x"),
            ToolCall(tool=f"t{i}"),
            Decision(effect=Effect.DENY, reason="no"),
        )
    return path


def test_empty_and_missing_trailing_newline(tmp_path: Path, log_path: Path) -> None:
    empty = tmp_path / "e.jsonl"
    empty.write_text("")
    assert verify_log(empty).ok
    assert verify_log(empty).entries == 0
    log_path.write_text(log_path.read_text().rstrip("\n"))
    assert verify_log(log_path).ok


def test_edited_field_is_hash_mismatch(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()
    lines[2] = lines[2].replace("deny", "allow")
    log_path.write_text("\n".join(lines) + "\n")
    result = verify_log(log_path)
    assert (result.ok, result.bad_seq, result.reason) == (False, 2, "hash_mismatch")


def test_deleted_middle_entry_is_gap(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()
    del lines[2]
    log_path.write_text("\n".join(lines) + "\n")
    result = verify_log(log_path)
    assert (result.bad_seq, result.reason) == (3, "gap")


def test_deleted_first_entry_is_gap(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()[1:]
    log_path.write_text("\n".join(lines) + "\n")
    assert verify_log(log_path).reason == "gap"


def test_swapped_entries_are_reordered(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    log_path.write_text("\n".join(lines) + "\n")
    result = verify_log(log_path)
    assert (result.bad_seq, result.reason) == (2, "reordered")


def test_duplicated_entry_is_reordered(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()
    lines.insert(2, lines[1])
    log_path.write_text("\n".join(lines) + "\n")
    assert verify_log(log_path).reason == "reordered"


def test_garbage_line_is_hash_mismatch(log_path: Path) -> None:
    with log_path.open("a") as fh:
        fh.write("not json\n")
    result = verify_log(log_path)
    assert (result.bad_seq, result.reason) == (5, "hash_mismatch")


def test_non_object_line_is_hash_mismatch(log_path: Path) -> None:
    with log_path.open("a") as fh:
        fh.write("[1]\n")
    assert verify_log(log_path).reason == "hash_mismatch"


def test_reformatted_whitespace_is_detected(log_path: Path) -> None:
    lines = log_path.read_text().splitlines()
    lines[1] = lines[1].replace('"seq":1}', '"seq": 1}')
    log_path.write_text("\n".join(lines) + "\n")
    assert verify_log(log_path).reason == "hash_mismatch"


def test_every_single_byte_change_is_detected(log_path: Path) -> None:
    original = log_path.read_bytes()
    for i in range(0, len(original), 7):
        mutated = bytearray(original)
        mutated[i] = ord("~") if mutated[i] != ord("~") else ord("!")
        log_path.write_bytes(bytes(mutated))
        assert not verify_log(log_path).ok, i
    log_path.write_bytes(original)
    assert verify_log(log_path).ok
