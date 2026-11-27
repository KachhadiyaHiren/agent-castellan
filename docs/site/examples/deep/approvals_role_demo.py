"""A rule with `approver: role:reviewer`, resolved through Guard.approve."""

from agent_castellan import Guard, ToolCall

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner")
coder, _ = guard.delegate(planner, "coder", tools=["fs.*"])
write = ToolCall(tool="fs.write", args={"path": "/workspace/app.py", "content": "x = 1"})

pending = guard.authorize(coder, write)
print("decision:", pending.effect.value, "| rule:", pending.rule_id)
print(
    "approve as 'reviewer-7':", guard.approve(pending.approval_id, approver_id="reviewer-7").value
)
