"""Call normalization, run before any matching (WS1; see PLAN.md §4.6)."""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..errors import PolicyError
from ..models import ToolCall

MAX_DEPTH = 32
MAX_BYTES = 1024 * 1024
MAX_TOOL_LENGTH = 256

PATH_KEYS = frozenset(
    {
        "path",
        "file",
        "filename",
        "filepath",
        "dir",
        "directory",
        "cwd",
        "target",
        "source",
        "dest",
        "destination",
    }
)
URL_KEYS = frozenset({"url", "uri", "endpoint"})
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}


def lexical_path(value: str) -> str:
    """Resolve `.` and `..` lexically and collapse repeated slashes; never raises."""
    value = unicodedata.normalize("NFC", value)
    if not value:
        return value
    resolved = posixpath.normpath(value)
    if resolved.startswith("//"):
        resolved = "/" + resolved.lstrip("/")
    return resolved


def _normalize_path(value: str) -> str:
    if "\x00" in value:
        raise PolicyError("path contains a NUL byte")
    if value.startswith("/"):
        depth = 0
        for part in value.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                depth -= 1
                if depth < 0:
                    raise PolicyError(f"path escapes above the root: {value!r}")
            else:
                depth += 1
    return lexical_path(value)


def _normalize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise PolicyError(f"invalid URL: {exc}") from exc
    if not parts.scheme or not parts.netloc or host is None:
        return value
    scheme = parts.scheme.lower()
    try:
        host = host.lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PolicyError(f"invalid host in URL: {host!r}") from exc
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"
    userinfo = parts.netloc.rpartition("@")[0]
    netloc = f"{userinfo}@{host}" if "@" in parts.netloc else host
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in PATH_KEYS or lowered.endswith("_path")


def _is_url_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in URL_KEYS or lowered.endswith("_url")


def _walk(value: Any, key: str | None, depth: int) -> Any:  # noqa: PLR0911
    if isinstance(value, str):
        if key is not None and _is_path_key(key):
            return _normalize_path(value)
        if key is not None and _is_url_key(key):
            return _normalize_url(value)
        return value
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PolicyError("arguments contain a non-finite number")
        return value
    if isinstance(value, dict | list | tuple) and depth > MAX_DEPTH:
        raise PolicyError(f"arguments nested deeper than {MAX_DEPTH} levels")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise PolicyError(f"argument keys must be strings, got {type(k).__name__}")
            out[k] = _walk(v, k, depth + 1)
        return out
    if isinstance(value, list | tuple):
        return [_walk(item, key, depth + 1) for item in value]
    raise PolicyError(f"arguments are not JSON-serializable: {type(value).__name__}")


def _normalize_tool(tool: str) -> str:
    name = tool.strip()
    if not name:
        raise PolicyError("tool name is empty")
    if len(name) > MAX_TOOL_LENGTH:
        raise PolicyError("tool name is too long")
    if name.isascii():
        if not name.isprintable() or " " in name:
            raise PolicyError("tool name contains control or whitespace characters")
    elif any(unicodedata.category(ch)[0] in "CZ" for ch in name):
        raise PolicyError("tool name contains control or whitespace characters")
    for _ in range(3):
        canon = unicodedata.normalize("NFKC", name).lower()
        if canon == name:
            break
        name = canon
    if name.startswith("mcp:"):
        server, sep, tool_part = name[4:].partition("/")
        if not server or not sep or not tool_part:
            raise PolicyError("MCP tool names must look like 'mcp:<server>/<tool>'")
    return name


def normalize_call(call: ToolCall) -> ToolCall:
    """Return the canonical form of a call, or raise PolicyError if it is invalid."""
    tool = _normalize_tool(call.tool)
    args = _walk(call.args, None, 1)
    resource = _walk(call.resource, None, 1)
    size = len(json.dumps(args, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    if size > MAX_BYTES:
        raise PolicyError(f"arguments larger than {MAX_BYTES} bytes")
    return ToolCall.model_construct(
        tool=tool, args=args, resource=resource, cost_units=call.cost_units
    )


def call_hash(call: ToolCall) -> str:
    """Return the SHA-256 hex digest of the canonical `{tool, args}` JSON."""
    normalized = normalize_call(call)
    payload = json.dumps(
        {"tool": normalized.tool, "args": normalized.args},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tool_namespace(tool: str) -> str:
    """Return the namespace of a normalized tool name (`mcp:server` for MCP tools)."""
    if tool.startswith("mcp:") and "/" in tool:
        return tool.split("/", 1)[0]
    return re.split(r"[.:]", tool, maxsplit=1)[0]
