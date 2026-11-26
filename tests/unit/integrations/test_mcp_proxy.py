from __future__ import annotations

import json
import os
import queue
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from agent_castellan.integrations import mcp_proxy
from agent_castellan.integrations.mcp_proxy import McpProxy, register, run_proxy
from agent_castellan.models import Effect

from .conftest import Rig, make_rig

pytest.importorskip("mcp")

SERVER = [sys.executable, str(Path(__file__).parent / "fixtures" / "echo_server.py")]
TIMEOUT = 20.0
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


class Session:
    """Drives `run_proxy` in a thread with pipes; every read has a timeout."""

    def __init__(self, proxy: McpProxy, command: list[str]) -> None:
        in_r, self._in_w = os.pipe()
        self._out_r, out_w = os.pipe()
        self._client_in = os.fdopen(in_r, "rb")
        self._client_out = os.fdopen(out_w, "wb")
        self._to_proxy = os.fdopen(self._in_w, "wb")
        self._from_proxy = os.fdopen(self._out_r, "rb")
        self.lines: queue.Queue[bytes] = queue.Queue()
        self.code: int | None = None
        self._runner = threading.Thread(target=self._run, args=(proxy, command), daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._runner.start()
        self._reader.start()

    def _run(self, proxy: McpProxy, command: list[str]) -> None:
        self.code = run_proxy(proxy, command, self._client_in, self._client_out)
        self._client_out.close()

    def _read(self) -> None:
        for line in self._from_proxy:
            self.lines.put(line)

    def send(self, message: dict[str, Any] | bytes) -> None:
        data = message if isinstance(message, bytes) else json.dumps(message).encode() + b"\n"
        self._to_proxy.write(data)
        self._to_proxy.flush()

    def recv_raw(self) -> bytes:
        return self.lines.get(timeout=TIMEOUT)

    def recv(self) -> dict[str, Any]:
        return json.loads(self.recv_raw())  # type: ignore[no-any-return]

    def close(self) -> None:
        self._to_proxy.close()
        self._runner.join(timeout=TIMEOUT)
        assert not self._runner.is_alive()


@pytest.fixture
def session_for() -> Iterator[Any]:
    sessions: list[Session] = []

    def build(rig: Rig, *, hide_denied: bool = False) -> Session:
        proxy = McpProxy(rig.guard, rig.principal, "echo", hide_denied=hide_denied)
        s = Session(proxy, SERVER)
        sessions.append(s)
        s.send(INIT)
        assert s.recv()["id"] == 1
        s.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return s

    yield build
    for s in sessions:
        s.close()


def call(request_id: int, name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def test_allowed_call_passes_through_to_server(session_for: Any) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ALLOW})
    s = session_for(rig)
    s.send(call(2, "echo", text="hi"))
    reply = s.recv()
    assert reply["id"] == 2
    assert reply["result"]["isError"] is False
    assert "echo:hi" in json.dumps(reply)
    entry = rig.audit.entries[-1]
    assert entry.call.tool == "mcp:echo/echo"
    assert entry.call.args == {"text": "hi"}


def test_denied_call_returns_is_error_with_reason_and_never_reaches_server(
    session_for: Any,
) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ALLOW})
    s = session_for(rig)
    s.send(call(2, "delete_all", confirm=True))
    reply = s.recv()
    assert reply["id"] == 2
    assert reply["result"]["isError"] is True
    assert "fake default" in reply["result"]["content"][0]["text"]
    assert "error" not in reply


def test_ask_returns_approval_id_and_retry_succeeds_after_approval(session_for: Any) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ASK})
    s = session_for(rig)
    s.send(call(2, "echo", text="x"))
    reply = s.recv()
    text = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is True
    assert text.startswith("approval required: appr-1; run `castellan approve accept")
    rig.guard.approve("appr-1", approver_id="reviewer")
    s.send(call(3, "echo", text="x"))
    assert s.recv()["result"]["isError"] is False


def test_non_tool_messages_are_relayed_byte_for_byte(session_for: Any) -> None:
    rig = make_rig({})
    s = session_for(rig)
    # Odd spacing and key order must survive untouched in what the server receives:
    # the server echoes unknown methods as errors that quote the method, so check that the
    # response for `ping` (a plain relayed request) is exactly what the server produced.
    s.send(b'{ "jsonrpc":"2.0",  "id": 7, "method":"ping" }\n')
    assert s.recv_raw() == b'{"jsonrpc":"2.0","id":7,"result":{}}\n'


def test_tools_list_is_unfiltered_by_default(session_for: Any) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ALLOW})
    s = session_for(rig)
    s.send({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    names = [t["name"] for t in s.recv()["result"]["tools"]]
    assert names == ["echo", "delete_all"]


def test_hide_denied_filters_tools_list(session_for: Any) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ALLOW})
    s = session_for(rig, hide_denied=True)
    s.send({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    reply = s.recv()
    assert [t["name"] for t in reply["result"]["tools"]] == ["echo"]
    # the listing check is a dry run: nothing audited for it
    assert rig.audit.entries == []


def test_hide_denied_keeps_ask_tools_visible(session_for: Any) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ASK})
    s = session_for(rig, hide_denied=True)
    s.send({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    assert [t["name"] for t in s.recv()["result"]["tools"]] == ["echo"]
    assert rig.approvals.requests == {}


def test_proxy_exits_when_client_closes(session_for: Any) -> None:
    rig = make_rig({})
    s = session_for(rig)
    s.close()
    assert s.code == 0


# ---- pure unit tests of the message handling -------------------------------------------------


def proxy_for(rig: Rig, **kw: Any) -> McpProxy:
    return McpProxy(rig.guard, rig.principal, "srv", **kw)


def line(message: Any) -> bytes:
    return json.dumps(message).encode() + b"\n"


def test_unparseable_line_is_rejected_not_forwarded() -> None:
    action = proxy_for(make_rig({})).on_client_line(b"{nope\n")
    assert action.forward is None
    assert json.loads(action.reply or b"")["error"]["code"] == -32700


def test_batch_with_tools_call_is_rejected_but_plain_batch_is_forwarded() -> None:
    proxy = proxy_for(make_rig({"mcp:srv/t": Effect.ALLOW}))
    bad = proxy.on_client_line(line([call(1, "t"), {"jsonrpc": "2.0", "id": 2, "method": "ping"}]))
    assert bad.forward is None
    assert json.loads(bad.reply or b"")["error"]["code"] == -32600
    ok = line([{"jsonrpc": "2.0", "id": 2, "method": "ping"}])
    assert proxy.on_client_line(ok).forward == ok


def test_non_object_message_is_rejected() -> None:
    action = proxy_for(make_rig({})).on_client_line(b"42\n")
    assert action.forward is None
    assert json.loads(action.reply or b"")["error"]["code"] == -32600


@pytest.mark.parametrize(
    "params",
    [None, {}, {"name": ""}, {"name": 5}, {"name": "t", "arguments": [1]}],
)
def test_invalid_tools_call_params_are_rejected(params: Any) -> None:
    rig = make_rig({"mcp:srv/t": Effect.ALLOW})
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    action = proxy_for(rig).on_client_line(line(msg))
    assert action.forward is None
    assert json.loads(action.reply or b"")["error"]["code"] == -32602
    assert rig.audit.entries == []


def test_tools_call_without_arguments_is_allowed() -> None:
    rig = make_rig({"mcp:srv/t": Effect.ALLOW})
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "t"}}
    assert proxy_for(rig).on_client_line(line(msg)).forward == line(msg)


def test_denied_notification_gets_no_reply_and_is_dropped() -> None:
    rig = make_rig({})
    msg = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "t"}}
    action = proxy_for(rig).on_client_line(line(msg))
    assert action.forward is None
    assert action.reply is None


def test_guard_exception_fails_closed() -> None:
    rig = make_rig({"mcp:srv/t": Effect.ALLOW})

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("store down")

    rig.guard.authorize = boom  # type: ignore[method-assign]
    action = proxy_for(rig).on_client_line(line(call(1, "t")))
    assert action.forward is None
    assert "authorization failed: store down" in (action.reply or b"").decode()


def test_ask_without_approval_id_is_a_denial() -> None:
    proxy = proxy_for(make_rig({}))
    from agent_castellan.models import Decision

    reply = proxy._refusal(1, Decision(effect=Effect.ASK, reason="r"))
    assert b"denied: approval needed" in reply


def test_server_lines_pass_unchanged_without_hide_denied() -> None:
    proxy = proxy_for(make_rig({}))
    raw = b'{ "id":1,"result":{"tools":[]}}\n'
    assert proxy.on_server_line(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        b"not json\n",
        b"[1]\n",
        b'{"jsonrpc":"2.0","method":"notifications/progress"}\n',
        b'{"jsonrpc":"2.0","id":99,"result":{"tools":[{"name":"x"}]}}\n',
        b'{"jsonrpc":"2.0","id":5,"error":{"code":1,"message":"m"}}\n',
        b'{"jsonrpc":"2.0","id":5,"result":{"tools":"weird"}}\n',
    ],
)
def test_hide_denied_leaves_unrelated_server_lines_alone(raw: bytes) -> None:
    proxy = proxy_for(make_rig({}), hide_denied=True)
    proxy.on_client_line(line({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}))
    assert proxy.on_server_line(raw) == raw


def test_hide_denied_keeps_malformed_tool_entries() -> None:
    proxy = proxy_for(make_rig({}), hide_denied=True)
    proxy.on_client_line(line({"jsonrpc": "2.0", "id": "a", "method": "tools/list"}))
    raw = line({"jsonrpc": "2.0", "id": "a", "result": {"tools": ["odd", {"name": 3}]}})
    assert json.loads(proxy.on_server_line(raw))["result"]["tools"] == ["odd", {"name": 3}]


def test_run_proxy_terminates_server_that_ignores_stdin_close(tmp_path: Path) -> None:
    stubborn = tmp_path / "stubborn.py"
    stubborn.write_text("import time\ntime.sleep(60)\n")
    rig = make_rig({})
    r, w = os.pipe()
    out = open(os.devnull, "wb")  # noqa: SIM115
    os.close(w)
    mcp_proxy._SHUTDOWN_WAIT, saved = 0.3, mcp_proxy._SHUTDOWN_WAIT
    try:
        code = run_proxy(proxy_for(rig), [sys.executable, str(stubborn)], os.fdopen(r, "rb"), out)
    finally:
        mcp_proxy._SHUTDOWN_WAIT = saved
        out.close()
    assert code != 0


def test_run_proxy_stops_when_server_exits_early(tmp_path: Path) -> None:
    quick = tmp_path / "quick.py"
    quick.write_text("import sys\nsys.exit(3)\n")
    rig = make_rig({})
    r, w = os.pipe()
    wf = os.fdopen(w, "wb")
    out = open(os.devnull, "wb")  # noqa: SIM115
    reader = os.fdopen(r, "rb")
    result: list[int] = []
    t = threading.Thread(
        target=lambda: result.append(
            run_proxy(proxy_for(rig), [sys.executable, str(quick)], reader, out)
        ),
        daemon=True,
    )
    t.start()
    for _ in range(200):  # keep writing until the broken pipe stops the proxy
        try:
            wf.write(line({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
            wf.flush()
        except OSError:
            break
        t.join(timeout=0.05)
        if not t.is_alive():
            break
    wf.close()
    t.join(timeout=TIMEOUT)
    assert result == [3]
    out.close()


# ---- CLI registration ------------------------------------------------------------------------


def test_cli_command_runs_proxy_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = make_rig({"mcp:echo/echo": Effect.ALLOW})
    seen: dict[str, Any] = {}

    def fake_build(policy: Path, state: Path | None) -> Any:
        seen["policy"], seen["state"] = policy, state
        return rig.guard

    monkeypatch.setattr(mcp_proxy, "build_guard", fake_build)
    app = typer.Typer()
    register(app)
    stdin = line(INIT) + line(call(3, "delete_all"))
    result = CliRunner().invoke(
        app,
        [
            "--policy",
            "p.yaml",
            "--role",
            "coder",
            "--server-name",
            "echo",
            "--state",
            str(tmp_path / "s.db"),
            "--",
            *SERVER,
        ],
        input=stdin,
    )
    assert result.exit_code == 0
    out = [json.loads(x) for x in result.stdout_bytes.splitlines()]
    by_id = {m["id"]: m for m in out}
    assert by_id[3]["result"]["isError"] is True
    assert seen["policy"] == Path("p.yaml")
    assert seen["state"] == tmp_path / "s.db"


def test_default_server_name_is_command_stem() -> None:
    assert mcp_proxy._default_server_name(["/usr/bin/npx", "x"]) == "npx"


def test_build_guard_delegates_to_guard_from_file(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(
        mcp_proxy.Guard, "from_file", classmethod(lambda cls, p, **k: seen.append((p, k)) or "g")
    )
    assert mcp_proxy.build_guard(Path("p.yaml"), None) == "g"
    assert seen == [(Path("p.yaml"), {"state_path": None})]
