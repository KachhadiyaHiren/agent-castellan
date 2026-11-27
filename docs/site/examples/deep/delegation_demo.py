"""Delegation walkthrough: grants shrink, widening fails, tokens cross processes."""

import base64
import json

from agent_castellan import GrantError, Guard, PermissionDenied, ToolCall
from agent_castellan.delegation.grants import chain_from_token, chain_to_token

KEY = bytes.fromhex("11" * 32)  # use a real secret in production
guard = Guard.from_file("team.yaml", key=KEY)
search = ToolCall(tool="web.search", args={"q": "castles"})
read = ToolCall(tool="fs.read", args={"path": "/workspace/a.txt"})

# The planner is the root: its power is whatever the policy gives it.
planner = guard.start_run("planner", on_behalf_of="alice")
researcher, grant = guard.delegate(planner, "researcher", tools=["web.*"], max_calls=5)
print("depth:", researcher.depth, "| parent:", researcher.parent_role)
print("grant tools:", grant.tools, "| max_calls:", grant.max_calls)

# 1. The grant narrows what the policy already allows (dry runs with check()).
for call in (search, read):
    d = guard.check(researcher, call)
    print(f"{call.tool:10} -> {d.effect.value:5} source={d.source}: {d.reason}")

# 2. A child can never gain power: widening is refused when the grant is minted.
try:
    guard.delegate(researcher, "researcher", tools=["web.search", "fs.read"])
except GrantError as exc:
    print("widening refused:", exc)
try:  # the default 900 s ttl starts later than the parent's, so it ends later: refused
    guard.delegate(researcher, "researcher", tools=["web.search"])
except GrantError as exc:
    print("longer life refused:", exc)
sub, _ = guard.delegate(
    researcher, "researcher", tools=["web.search"], ttl_seconds=300, max_calls=2
)
print("narrowing ok: sub-agent depth", sub.depth)

# 3. Roles may only delegate where the policy says so.
try:
    guard.delegate(researcher, "coder", tools=["web.search"])
except PermissionDenied as exc:
    print("role rule:", exc)

# 4. Tokens: serialize the chain, send it anywhere, parse it back.
chain = chain_to_token(guard._chains[researcher.agent_id])  # the chain Guard stored
print("token chars:", len(chain), "| grants:", chain.count(".") + 1)
restored = chain_from_token(chain)
print("restored chain ->", guard.check(researcher, search, chain=restored).effect.value)

# 5. Tampering with a token breaks the signature.
part = chain.split(".")[0]
body = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
body["tools"] = ["**"]  # try to widen
forged = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
d = guard.check(researcher, search, chain=chain_from_token(forged))
print("forged token ->", d.effect.value, "|", d.reason)

# 6. A verifier with a different root key rejects a valid chain.
other = Guard.from_file("team.yaml", key=bytes.fromhex("22" * 32))
d = other.check(researcher, search, chain=restored)
print("wrong key ->", d.effect.value, "|", d.reason)

# 7. A grant chain is only valid for the agent it was issued to.
d = guard.check(sub, search, chain=restored)
print("someone else's chain ->", d.effect.value, "|", d.reason)
