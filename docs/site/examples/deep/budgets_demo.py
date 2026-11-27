"""Budget walkthrough: run-tree, per-role and cost limits (see team.yaml `budgets`)."""

from agent_castellan import Guard, ToolCall

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner")
r1, _ = guard.delegate(planner, "researcher", tools=["web.*"])
r2, _ = guard.delegate(planner, "researcher", tools=["web.*"])
coder, _ = guard.delegate(planner, "coder", tools=["fs.*"])

search = ToolCall(tool="web.search", args={"q": "castles"})
read = ToolCall(tool="fs.read", args={"path": "/workspace/a.txt"})


def show(label, who, call):
    d = guard.authorize(who, call)
    print(f"{label:22} {d.effect.value:5} {d.source:7} {d.reason}")


# Per-role limit (3) is shared by every researcher in the run, not per agent.
show("researcher 1, call 1", r1, search)
show("researcher 1, call 2", r1, search)
show("researcher 2, call 3", r2, search)
show("researcher 2, call 4", r2, search)

# Run limit (6) is shared by the whole tree. Three calls used so far.
show("coder, call 4 (run)", coder, read)
show("coder, call 5 (run)", coder, read)
show("coder, call 6 (run)", coder, read)
show("coder, call 7 (run)", coder, read)

print()
usage = guard._budgets.usage(planner.run_id)  # internal accessor: counters per scope
print({k: v for k, v in usage.items() if not k.startswith("agent.")})
