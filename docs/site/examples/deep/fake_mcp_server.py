"""A tiny MCP-style server (newline-delimited JSON-RPC over stdio) used by the guides.

It has three tools and no dependencies, so the proxy demo runs anywhere.
"""

import json
import sys

TOOLS = [
    {"name": "read_file", "description": "Read a file", "inputSchema": {"type": "object"}},
    {"name": "write_file", "description": "Write a file", "inputSchema": {"type": "object"}},
    {"name": "delete_file", "description": "Delete a file", "inputSchema": {"type": "object"}},
]

for line in sys.stdin:
    message = json.loads(line)
    method, request_id = message.get("method"), message.get("id")
    if request_id is None:  # notification: no reply
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "files", "version": "0.1"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = message["params"]["name"]
        text = f"server ran {name} with {json.dumps(message['params'].get('arguments'))}"
        result = {"content": [{"type": "text", "text": text}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
