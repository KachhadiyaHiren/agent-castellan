"""Process B (the worker): rebuild the principal, present the chain, make calls."""

import json
import sys

from agent_castellan import GrantError, Guard, Principal, ToolCall
from agent_castellan.delegation.grants import chain_from_token

handoff = json.loads(sys.stdin.readline())
me = Principal(**handoff["principal"])
chain = chain_from_token(handoff["chain"])
guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))

for tool, args in [("web.search", {"q": "castles"}), ("fs.read", {"path": "/workspace/a.txt"})]:
    d = guard.authorize(me, ToolCall(tool=tool, args=args), chain=chain)
    print(f"{tool:10} -> {d.effect.value:5} source={d.source}")

d = guard.authorize(me, ToolCall(tool="web.search", args={"q": "x"}))  # forgot the chain
print("no chain   ->", d.effect.value, "|", d.reason)

try:
    guard.delegate(me, "researcher", tools=["web.search"])
except GrantError as exc:
    print("delegate in B:", exc)
