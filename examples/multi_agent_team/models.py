"""The model layer: a tiny ``ChatModel`` protocol and two implementations.

Agents talk to a model in a very small JSON protocol, so the same loop works with
a scripted model (deterministic, used in tests and CI) and with any
OpenAI-compatible chat endpoint (no vendor SDK needed).

A model reply is one JSON object, one of:

``{"action": "call", "tool": "fs.read", "args": {"path": "/workspace/README.md"}}``
    Ask to run a tool. Castellan decides first.
``{"action": "delegate", "role": "coder", "tools": ["fs.read"], "task": "..."}``
    Hand a sub-task to a new agent with a narrower grant.
``{"action": "final", "text": "..."}``
    Finish and return an answer.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Message:
    """One chat message: ``role`` is ``system``, ``user`` or ``assistant``."""

    role: str
    content: str


class ChatModel(Protocol):
    """Anything that turns a conversation into the next reply text."""

    def complete(self, messages: Sequence[Message]) -> str:
        """Return the next assistant reply for these messages."""
        ...


# --- the action protocol -------------------------------------------------------------------


@dataclass(frozen=True)
class CallAction:
    """The model wants to run a tool."""

    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class DelegateAction:
    """The model wants to hand a task to a new agent."""

    role: str
    tools: tuple[str, ...]
    task: str


@dataclass(frozen=True)
class FinalAction:
    """The model is done and returns text."""

    text: str


Action = CallAction | DelegateAction | FinalAction


def call(tool: str, **args: Any) -> str:
    """Build the JSON reply text for a tool call (used by scripts)."""
    return json.dumps({"action": "call", "tool": tool, "args": args})


def delegate(role: str, tools: Sequence[str], task: str) -> str:
    """Build the JSON reply text for a delegation (used by scripts)."""
    return json.dumps({"action": "delegate", "role": role, "tools": list(tools), "task": task})


def final(text: str) -> str:
    """Build the JSON reply text for a final answer (used by scripts)."""
    return json.dumps({"action": "final", "text": text})


def parse_action(reply: str) -> Action:
    """Parse a model reply into an action; anything unparseable becomes a final answer.

    Real models often wrap JSON in prose or code fences, so the first ``{...}`` block
    is extracted before parsing.
    """
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        return FinalAction(reply.strip())
    try:
        data = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return FinalAction(reply.strip())
    if not isinstance(data, dict):
        return FinalAction(reply.strip())
    kind = data.get("action")
    if kind == "call" and isinstance(data.get("tool"), str):
        args = data.get("args")
        return CallAction(data["tool"], args if isinstance(args, dict) else {})
    if kind == "delegate" and isinstance(data.get("role"), str):
        tools = data.get("tools")
        names = tuple(str(t) for t in tools) if isinstance(tools, list) else ()
        return DelegateAction(data["role"], names, str(data.get("task", "")))
    return FinalAction(str(data.get("text", reply.strip())))


# --- implementations -----------------------------------------------------------------------


class ScriptedModel:
    """A deterministic model that replays a fixed list of replies, one per call.

    It ignores the conversation. That is the point: scenarios are reproducible, and
    what is under test is Castellan's decision, not a language model's behaviour.
    """

    def __init__(self, steps: Sequence[str]) -> None:
        self._steps = list(steps)
        self._next = 0

    def complete(self, messages: Sequence[Message]) -> str:
        """Return the next scripted reply, or a final answer when the script ends."""
        if self._next >= len(self._steps):
            return final("(script finished)")
        reply = self._steps[self._next]
        self._next += 1
        return reply


PostFn = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _httpx_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    httpx = importlib.import_module("httpx")  # imported lazily: only this model needs it
    response = httpx.post(url, headers=headers, json=body, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("chat endpoint returned something other than a JSON object")
    return data


class OpenAICompatibleModel:
    """Talks to any OpenAI-compatible ``/chat/completions`` endpoint over HTTP.

    Configure it with environment variables (see :meth:`from_env`). It uses ``httpx``
    directly, so no vendor SDK is installed or imported.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        post: PostFn | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._post = post or _httpx_post

    @classmethod
    def from_env(cls) -> OpenAICompatibleModel:
        """Build a model from ``CASTELLAN_EXAMPLE_BASE_URL``, ``..._MODEL`` and ``..._API_KEY``.

        Raises:
            RuntimeError: if the base URL or model name is not set.
        """
        base_url = os.environ.get("CASTELLAN_EXAMPLE_BASE_URL")
        model = os.environ.get("CASTELLAN_EXAMPLE_MODEL")
        if not base_url or not model:
            raise RuntimeError(
                "set CASTELLAN_EXAMPLE_BASE_URL and CASTELLAN_EXAMPLE_MODEL "
                "(and CASTELLAN_EXAMPLE_API_KEY if the endpoint needs one)"
            )
        return cls(base_url, model, os.environ.get("CASTELLAN_EXAMPLE_API_KEY"))

    def complete(self, messages: Sequence[Message]) -> str:
        """Send the conversation and return the first choice's text."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self._model,
            "temperature": 0,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        data = self._post(self._url, headers, body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected reply from chat endpoint: {data!r:.200}") from exc
        return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(content))
