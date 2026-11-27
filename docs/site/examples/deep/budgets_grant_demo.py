"""Per-grant max_calls: the value is signed into the grant, but see the note in the guide."""

from agent_castellan import Guard, ToolCall

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner")
coder, grant = guard.delegate(planner, "coder", tools=["fs.*"], max_calls=1)
print("grant max_calls:", grant.max_calls)
for n in (1, 2):
    d = guard.authorize(coder, ToolCall(tool="fs.read", args={"path": "/workspace/a.txt"}))
    print(f"call {n}: {d.effect.value}")
