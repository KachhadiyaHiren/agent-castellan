# ruff: noqa: S603, S607
"""Drive `castellan mcp-proxy` the way an MCP client would, and print what comes back."""

import json
import os
import subprocess
import sys

extra = ["--hide-denied"] if "--hide-denied" in sys.argv else []
env = {**os.environ, "CASTELLAN_KEY": "11" * 32}  # silences the random-key warning

proxy = subprocess.Popen(
    [
        "castellan",
        "mcp-proxy",
        "--policy",
        "mcp-policy.yaml",
        "--role",
        "assistant",
        "--server-name",
        "files",
        "--state",
        "mcp-state.db",
        *extra,
        "--",
        sys.executable,
        "fake_mcp_server.py",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    env=env,
)


def rpc(request_id, method, params=None):
    proxy.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        + "\n"
    )
    proxy.stdin.flush()
    return json.loads(proxy.stdout.readline())


def call(request_id, tool, **arguments):
    reply = rpc(request_id, "tools/call", {"name": tool, "arguments": arguments})
    result = reply["result"]
    flag = "ERROR" if result.get("isError") else "ok"
    print(f"{tool}({arguments}) -> [{flag}] {result['content'][0]['text']}")


rpc(1, "initialize")
tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
print("tools/list shows:", tools)
call(3, "read_file", path="/srv/docs/readme.md")
call(4, "read_file", path="/srv/docs/.env")
call(5, "write_file", path="/srv/docs/readme.md", content="hi")
call(6, "delete_file", path="/srv/docs/readme.md")
proxy.stdin.close()
proxy.wait()
