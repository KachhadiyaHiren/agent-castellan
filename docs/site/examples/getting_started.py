import secrets

from agent_castellan import Guard, ToolCall

# One key per deployment. Grants signed with it only verify with the same key.
guard = Guard.from_file("first-policy.yaml", key=secrets.token_bytes(32))

# --- A root agent: the planner starts a run on behalf of a user -------------
planner = guard.start_run("planner", on_behalf_of="alice")
print("principal:", planner.role, "depth", planner.depth, "run", planner.run_id[:8] + "...")

# --- Allow ------------------------------------------------------------------
read = ToolCall(tool="fs.read", args={"path": "/workspace/app.py"})
decision = guard.authorize(planner, read)
print(decision.effect.value, decision.rule_id, "-", decision.reason)

# --- Deny -------------------------------------------------------------------
secret = ToolCall(tool="fs.read", args={"path": "/workspace/.env"})
decision = guard.authorize(planner, secret)
print(decision.effect.value, decision.rule_id, "-", decision.reason)

# --- Delegation: the coder gets a grant that can only read ------------------
coder, grant = guard.delegate(planner, "coder", tools=["fs.read"], ttl_seconds=600)
print("coder depth:", coder.depth, "| grant tools:", list(grant.tools))

write = ToolCall(tool="fs.write", args={"path": "/workspace/app.py", "content": "print('hi')"})
decision = guard.authorize(coder, write)
print(decision.effect.value, decision.source, "-", decision.reason)

# --- Ask: a coder with a wider grant must get approval ----------------------
coder2, _ = guard.delegate(planner, "coder", tools=["fs.*"], ttl_seconds=600)
decision = guard.authorize(coder2, write)
print(decision.effect.value, decision.rule_id, "approval_id set:", decision.approval_id is not None)

status = guard.approve(decision.approval_id, approver_id="alice")
print("approval status:", status.value)

decision = guard.authorize(coder2, write)  # retry the exact same call
print(decision.effect.value, decision.source, "-", decision.reason)

decision = guard.authorize(coder2, write)  # approvals are single-use
print(decision.effect.value, "(a second retry asks again)")
