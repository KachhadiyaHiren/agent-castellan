from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from agent_castellan.audit import (
    GENESIS_HASH,
    AuditLog,
    iter_entries,
    tail_entries,
    verify_log,
)
from agent_castellan.models import Decision, Effect, Principal, ToolCall
from agent_castellan.testing.fakes import FrozenClock


def _p(run: str = "r1") -> Principal:
    return Principal(agent_id="a1", role="coder", run_id=run)


def _d() -> Decision:
    return Decision(effect=Effect.ALLOW, reason="ok", rule_id="r")


def _fill(log: AuditLog, n: int, run: str = "r1") -> None:
    for i in range(n):
        log.append(_p(run), ToolCall(tool=f"fs.read{i}", args={"p": "é"}), _d())


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _worker(path: str, run: str) -> None:
    _fill(AuditLog(path, FrozenClock(), fsync=False), 25, run)


def test_first_entry_uses_genesis_hash(tmp_path: Path) -> None:
    entry = AuditLog(tmp_path / "a.jsonl", FrozenClock()).append(_p(), ToolCall(tool="x"), _d())
    assert entry.seq == 0
    assert entry.prev_hash == GENESIS_HASH


def test_entries_are_chained_and_verify(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "a.jsonl"
    _fill(AuditLog(path, FrozenClock()), 5)
    entries = list(iter_entries(path))
    assert [e.seq for e in entries] == [0, 1, 2, 3, 4]
    assert entries[3].prev_hash == entries[2].hash
    assert verify_log(path).ok


def test_new_writer_continues_existing_chain(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    _fill(AuditLog(path, FrozenClock(), fsync=False), 2)
    _fill(AuditLog(path, FrozenClock(), fsync=False), 2)
    assert verify_log(path).entries == 4


def test_long_last_line_is_found(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, FrozenClock())
    log.append(_p(), ToolCall(tool="x", args={"blob": "z" * 20000}), _d())
    log.append(_p(), ToolCall(tool="y"), _d())
    assert verify_log(path).ok


def test_multiprocess_writers_keep_chain_valid(tmp_path: Path) -> None:
    path = str(tmp_path / "a.jsonl")
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(path, f"r{i}")) for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    result = verify_log(path)
    assert result.ok
    assert result.entries == 100


def test_iter_and_tail_filter_by_run(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, FrozenClock(), fsync=False)
    _fill(log, 3, "r1")
    _fill(log, 2, "r2")
    assert len(list(iter_entries(path, "r2"))) == 2
    assert [e.seq for e in tail_entries(path, 2)] == [3, 4]
    assert [e.seq for e in tail_entries(path, 10, "r1")] == [0, 1, 2]
    assert tail_entries(path, 0) == []


def test_blank_lines_are_ignored_by_reader(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    _fill(AuditLog(path, FrozenClock()), 1)
    with path.open("a") as fh:
        fh.write("\n\n")
    assert len(list(iter_entries(path))) == 1
    assert verify_log(path).ok


def test_trailing_blank_lines_do_not_break_appending(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, FrozenClock())
    _fill(log, 1)
    with path.open("a") as fh:
        fh.write("\n")
    _fill(log, 1)
    assert verify_log(path).ok


def test_log_lines_are_canonical_json(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    _fill(AuditLog(path, FrozenClock()), 1)
    line = _lines(path)[0]
    assert line == json.dumps(
        json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


@pytest.mark.parametrize("fsync", [True, False])
def test_fsync_flag_both_work(tmp_path: Path, fsync: bool) -> None:
    path = tmp_path / "a.jsonl"
    _fill(AuditLog(path, FrozenClock(), fsync=fsync), 2)
    assert verify_log(path).ok
