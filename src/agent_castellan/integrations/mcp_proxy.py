"""Stdio MCP proxy that enforces policy on `tools/call` (WS5).

The proxy speaks newline-delimited JSON-RPC (the MCP stdio transport) and does not need the
`mcp` SDK. Messages it does not care about are relayed as the exact bytes it received.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import typer

from ..guard import Guard
from ..models import Decision, Effect, Principal, ToolCall

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INVALID_PARAMS = -32602
_SHUTDOWN_WAIT = 5.0


@dataclass(frozen=True)
class ClientAction:
    """What to do with one client line: send `forward` to the server, `reply` to the client."""

    forward: bytes | None = None
    reply: bytes | None = None


def _dump(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def _error(request_id: Any, code: int, message: str) -> bytes:
    return _dump({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _is_tools_call(message: Any) -> bool:
    return isinstance(message, dict) and message.get("method") == "tools/call"


class McpProxy:
    """Decides, message by message, what passes between an MCP client and a real server."""

    def __init__(
        self,
        guard: Guard,
        principal: Principal,
        server_name: str,
        *,
        hide_denied: bool = False,
        approve_hint: str = "castellan approve accept",
    ) -> None:
        self._guard = guard
        self._principal = principal
        self._server = server_name
        self._hide_denied = hide_denied
        self._approve_hint = approve_hint
        self._list_ids: set[str] = set()
        self._lock = threading.Lock()

    def tool_name(self, tool: str) -> str:
        """Return the policy-facing name `mcp:<server>/<tool>` for a server tool."""
        return f"mcp:{self._server}/{tool}"

    def on_client_line(self, line: bytes) -> ClientAction:
        """Inspect one client-to-server line."""
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            # Cannot prove it is not a tool call, so it never reaches the server.
            return ClientAction(reply=_error(None, PARSE_ERROR, "parse error"))
        if isinstance(message, list):
            if any(_is_tools_call(item) for item in message):
                return ClientAction(
                    reply=_error(None, INVALID_REQUEST, "batched tools/call is not supported")
                )
            return ClientAction(forward=line)
        if not isinstance(message, dict):
            return ClientAction(reply=_error(None, INVALID_REQUEST, "invalid request"))
        method = message.get("method")
        if method == "tools/call":
            return self._on_tool_call(message, line)
        if method == "tools/list" and self._hide_denied and "id" in message:
            with self._lock:
                self._list_ids.add(json.dumps(message["id"]))
        return ClientAction(forward=line)

    def _on_tool_call(self, message: dict[str, Any], line: bytes) -> ClientAction:
        request_id = message.get("id")
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        arguments = params.get("arguments") if isinstance(params, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or not (arguments is None or isinstance(arguments, dict))
        ):
            return ClientAction(
                reply=_error(request_id, INVALID_PARAMS, "invalid tools/call params")
            )
        try:
            call = ToolCall(tool=self.tool_name(name), args=arguments or {})
            decision = self._guard.authorize(self._principal, call)
        except Exception as exc:
            decision = Decision(
                effect=Effect.DENY, reason=f"authorization failed: {exc}", source="invalid"
            )
        if decision.effect is Effect.ALLOW:
            return ClientAction(forward=line)
        if "id" not in message:
            return ClientAction()  # a denied notification has nobody to answer
        return ClientAction(reply=self._refusal(request_id, decision))

    def _refusal(self, request_id: Any, decision: Decision) -> bytes:
        if decision.effect is Effect.ASK and decision.approval_id:
            text = f"approval required: {decision.approval_id}; run `{self._approve_hint} "
            text += f"{decision.approval_id}`"
        elif decision.effect is Effect.ASK:
            text = "denied: approval needed but no request could be created"
        else:
            text = f"denied: {decision.reason}"
        result = {"content": [{"type": "text", "text": text}], "isError": True}
        return _dump({"jsonrpc": "2.0", "id": request_id, "result": result})

    def on_server_line(self, line: bytes) -> bytes:
        """Inspect one server-to-client line; usually returned unchanged."""
        if not self._hide_denied or not self._list_ids:
            return line
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            return line
        if not isinstance(message, dict) or "id" not in message or "method" in message:
            return line
        key = json.dumps(message["id"])
        with self._lock:
            if key not in self._list_ids:
                return line
            self._list_ids.discard(key)
        result = message.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return line
        tools = result["tools"]
        result["tools"] = [t for t in tools if not self._hidden(t)]
        return _dump(message)

    def _hidden(self, tool: Any) -> bool:
        name = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(name, str):
            return False
        decision = self._guard.check(self._principal, ToolCall(tool=self.tool_name(name)))
        return decision.effect is Effect.DENY


def run_proxy(
    proxy: McpProxy,
    command: Sequence[str],
    client_in: IO[bytes],
    client_out: IO[bytes],
) -> int:
    """Run the server command and relay messages until either side closes; return its exit code."""
    child = subprocess.Popen(  # noqa: S603 - the command is the user's explicit choice
        list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert child.stdin is not None  # noqa: S101
    assert child.stdout is not None  # noqa: S101
    out_lock = threading.Lock()

    def write_client(data: bytes) -> None:
        with out_lock:
            client_out.write(data)
            client_out.flush()

    def pump_server() -> None:
        assert child.stdout is not None  # noqa: S101
        for line in child.stdout:
            write_client(proxy.on_server_line(line))

    reader = threading.Thread(target=pump_server, daemon=True)
    reader.start()
    server_in = child.stdin
    try:
        for raw in client_in:
            if not raw.strip():
                continue
            action = proxy.on_client_line(raw if raw.endswith(b"\n") else raw + b"\n")
            if action.reply is not None:
                write_client(action.reply)
            if action.forward is not None:
                try:
                    server_in.write(action.forward)
                    server_in.flush()
                except (BrokenPipeError, OSError):
                    break
    finally:
        with contextlib.suppress(BrokenPipeError, OSError):
            server_in.close()
        try:
            child.wait(timeout=_SHUTDOWN_WAIT)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=_SHUTDOWN_WAIT)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        reader.join(timeout=_SHUTDOWN_WAIT)
    return child.returncode or 0


def build_guard(policy: Path, state: Path | None) -> Guard:
    """Build the real `Guard` from a policy file (separate so tests can replace it)."""
    return Guard.from_file(policy, state_path=state)


def _default_server_name(command: Sequence[str]) -> str:
    return Path(command[0]).stem or "server"


def register(app: typer.Typer) -> None:
    """Register the `mcp-proxy` command on the CLI app."""

    @app.command(
        "mcp-proxy",
        help="Run an MCP server behind a policy-enforcing stdio proxy: "
        "castellan mcp-proxy --policy team.yaml --role coder -- <server command...>",
    )
    def mcp_proxy(
        server_command: list[str] = typer.Argument(..., help="Server command (after `--`)."),
        policy: Path = typer.Option(..., "--policy", help="Policy YAML file."),
        role: str = typer.Option(..., "--role", help="Role the proxied client acts as."),
        server_name: str | None = typer.Option(
            None, "--server-name", help="Name used in tool names (default: command name)."
        ),
        hide_denied: bool = typer.Option(
            False, "--hide-denied", help="Hide tools the role can never use from tools/list."
        ),
        state: Path | None = typer.Option(None, "--state", help="SQLite state path."),
        on_behalf_of: str | None = typer.Option(None, "--on-behalf-of", help="End-user id."),
    ) -> None:
        guard = build_guard(policy, state)
        principal = guard.start_run(role, on_behalf_of=on_behalf_of)
        hint = "castellan approve accept"
        if state is not None:
            hint += f" --state {state}"
        proxy = McpProxy(
            guard,
            principal,
            server_name or _default_server_name(server_command),
            hide_denied=hide_denied,
            approve_hint=hint,
        )
        code = run_proxy(proxy, server_command, sys.stdin.buffer, _stdout_buffer())
        raise typer.Exit(code)


def _stdout_buffer() -> IO[bytes]:
    return sys.stdout.buffer if hasattr(sys.stdout, "buffer") else os.fdopen(1, "wb", closefd=False)
