"""Cost units: the caller reports what each call costs; the run limit is 10 units."""

from agent_castellan import Guard, ToolCall

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner")
coder, _ = guard.delegate(planner, "coder", tools=["fs.*"])

for cost in (4.0, 4.0, 4.0, 2.0):
    call = ToolCall(tool="fs.read", args={"path": "/workspace/a.txt"}, cost_units=cost)
    d = guard.authorize(coder, call)
    print(f"cost {cost:>3}: {d.effect.value:5} {d.reason}")
