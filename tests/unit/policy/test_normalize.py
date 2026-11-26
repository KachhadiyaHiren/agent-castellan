# ruff: noqa: RUF001
"""Call normalization: names, paths, URLs, limits and hashing."""

from __future__ import annotations

import pytest

from agent_castellan.errors import PolicyError
from agent_castellan.models import ToolCall
from agent_castellan.policy.normalize import (
    call_hash,
    lexical_path,
    normalize_call,
    tool_namespace,
)


def norm(tool: str = "fs.read", **args: object) -> ToolCall:
    return normalize_call(ToolCall(tool=tool, args=dict(args)))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FS.Read", "fs.read"),
        ("  fs.read  ", "fs.read"),
        ("ＦＳ.ｗｒｉｔｅ", "fs.write"),  # fullwidth letters fold to ASCII
        ("MCP:Files/Read_File", "mcp:files/read_file"),
    ],
)
def test_tool_names_are_lowercased_and_folded(raw: str, expected: str) -> None:
    assert normalize_call(ToolCall(tool=raw)).tool == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "fs\x00read",
        "fs\nread",
        "fs. read",
        "fs\u200b.read",
        "a\u00a0b",
        "x" * 300,
        "mcp:",
        "mcp:server",
        "mcp:/tool",
        "mcp:server/",
    ],
)
def test_invalid_tool_names_are_rejected(bad: str) -> None:
    with pytest.raises(PolicyError):
        normalize_call(ToolCall(tool=bad))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/workspace/a/../b", "/workspace/b"),
        ("/workspace/./a//b/", "/workspace/a/b"),
        ("//workspace/a", "/workspace/a"),
        ("/workspace/a/b/../../c", "/workspace/c"),
        ("rel/../x", "x"),
        ("../x", "../x"),
        ("/", "/"),
        ("", ""),
        ("/café", "/café"),  # NFC
    ],
)
def test_path_arguments_are_resolved_lexically(raw: str, expected: str) -> None:
    assert norm(path=raw).args["path"] == expected


@pytest.mark.parametrize("key", ["path", "FILE", "filename", "filepath", "dir", "directory"])
@pytest.mark.parametrize("key2", ["cwd", "target", "source", "dest", "destination", "out_path"])
def test_all_path_keys_are_normalized(key: str, key2: str) -> None:
    call = norm(**{key: "/a/../b", key2: "/c/./d"})
    assert call.args[key] == "/b"
    assert call.args[key2] == "/c/d"


@pytest.mark.parametrize("bad", ["/../etc/passwd", "/a/../../etc", "/workspace/../../x", "/a\x00b"])
def test_paths_escaping_root_or_with_nul_are_invalid(bad: str) -> None:
    with pytest.raises(PolicyError):
        norm(path=bad)


def test_non_path_keys_are_left_alone() -> None:
    assert norm(content="/a/../b", note="A\x00B").args == {"content": "/a/../b", "note": "A\x00B"}


def test_nested_and_list_paths_are_normalized() -> None:
    call = norm(opts={"file": "/a/../b"}, items=[{"path": "/x/./y"}], path=["/p/../q", "/r"])
    assert call.args == {
        "opts": {"file": "/b"},
        "items": [{"path": "/x/y"}],
        "path": ["/q", "/r"],
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443/Path?Q=1#F", "https://example.com/Path?Q=1#F"),
        ("http://example.com:80/", "http://example.com/"),
        ("http://example.com:8080/", "http://example.com:8080/"),
        ("https://bücher.example/x", "https://xn--bcher-kva.example/x"),
        ("https://user:pw@Example.com:443/x", "https://user:pw@example.com/x"),
        ("http://[::1]:80/x", "http://[::1]/x"),
        ("http://[::1]:9000/x", "http://[::1]:9000/x"),
        ("not a url", "not a url"),
        ("/just/a/path", "/just/a/path"),
    ],
)
def test_urls_are_canonicalized(raw: str, expected: str) -> None:
    assert norm(url=raw).args["url"] == expected


@pytest.mark.parametrize("key", ["url", "URI", "endpoint", "callback_url"])
def test_all_url_keys_are_canonicalized(key: str) -> None:
    assert norm(**{key: "HTTP://A.com:80"}).args[key] == "http://a.com"


@pytest.mark.parametrize("bad", ["http://host:99999/", "http://[::1/", "http://a℀b.com/"])
def test_malformed_urls_are_invalid(bad: str) -> None:
    with pytest.raises(PolicyError):
        norm(url=bad)


def test_invalid_idna_host_is_rejected() -> None:
    with pytest.raises(PolicyError):
        norm(url="http://" + "a" * 70 + ".com/")


@pytest.mark.parametrize(
    "args",
    [
        {"x": object()},
        {"x": b"bytes"},
        {"x": float("nan")},
        {"x": float("inf")},
        {1: "int key"},
        {"x": {1: 2}},
    ],
)
def test_non_json_args_are_rejected(args: dict[object, object]) -> None:
    with pytest.raises(PolicyError):
        normalize_call(ToolCall.model_construct(tool="t", args=args, resource={}, cost_units=0))


def test_depth_limit() -> None:
    deep: object = "leaf"
    for _ in range(31):
        deep = {"k": deep}
    norm(x=deep)  # exactly at the limit is fine
    with pytest.raises(PolicyError):
        norm(x={"k": deep})


def test_size_limit() -> None:
    norm(x="a" * 1000)
    with pytest.raises(PolicyError):
        norm(x="a" * (1024 * 1024))


def test_tuples_become_lists_and_other_fields_are_kept() -> None:
    call = normalize_call(
        ToolCall(tool="t", args={"a": (1, 2.5, None, True)}, resource={"r": 1}, cost_units=3.0)
    )
    assert call.args == {"a": [1, 2.5, None, True]}
    assert call.resource == {"r": 1}
    assert call.cost_units == 3.0


@pytest.mark.parametrize(
    "call",
    [
        ToolCall(tool="FS.Write", args={"path": "/a/../b", "n": [1, {"x": "é"}]}),
        ToolCall(tool="mcp:S/T", args={"url": "HTTP://X.com:80/", "file": "//a/./b"}),
        ToolCall(tool="İ.x"),
    ],
)
def test_normalization_is_idempotent(call: ToolCall) -> None:
    once = normalize_call(call)
    assert normalize_call(once) == once


def test_call_hash_is_stable_and_ignores_key_order_and_spelling() -> None:
    a = ToolCall(tool="FS.write", args={"path": "/x/../y", "b": 1, "a": 2})
    b = ToolCall(tool="fs.write", args={"a": 2, "b": 1, "path": "/y"})
    assert call_hash(a) == call_hash(b)
    assert len(call_hash(a)) == 64
    assert call_hash(a) != call_hash(ToolCall(tool="fs.write", args={"path": "/z"}))


def test_call_hash_ignores_cost_and_resource() -> None:
    a = ToolCall(tool="t", args={"a": 1}, cost_units=5, resource={"x": 1})
    assert call_hash(a) == call_hash(ToolCall(tool="t", args={"a": 1}))


def test_call_hash_does_not_escape_unicode() -> None:
    import hashlib

    expected = hashlib.sha256('{"args":{"a":"é"},"tool":"t"}'.encode()).hexdigest()
    assert call_hash(ToolCall(tool="t", args={"a": "é"})) == expected


@pytest.mark.parametrize(
    ("tool", "namespace"),
    [
        ("fs.read", "fs"),
        ("github:create_issue", "github"),
        ("mcp:files/read_file", "mcp:files"),
        ("plain", "plain"),
        ("mcp:odd", "mcp"),
    ],
)
def test_tool_namespace(tool: str, namespace: str) -> None:
    assert tool_namespace(tool) == namespace


def test_lexical_path_never_raises() -> None:
    assert lexical_path("/../../x") == "/x"
