# ruff: noqa: S603, S607
"""Approval walkthrough: ask -> approve -> retry, exact-call binding, expiry."""

import pathlib
import subprocess
import time

from agent_castellan import Guard, ToolCall

KEY = bytes.fromhex("11" * 32)
guard = Guard.from_file("team.yaml", key=KEY, state_path="approvals-state.db")
planner = guard.start_run("planner")
coder, _ = guard.delegate(planner, "coder", tools=["fs.*", "ops.*"])

deploy = ToolCall(tool="ops.deploy", args={"env": "staging", "version": "1.4.2"})

# 1. First attempt: the rule says `ask`, so Castellan opens a request and returns it.
first = guard.authorize(coder, deploy)
print(
    "first try :",
    first.effect.value,
    "| rule:",
    first.rule_id,
    "| id starts:",
    first.approval_id[:5],
)

# 2. The agent may not approve its own request.
print("self-approve:", guard.approve(first.approval_id, approver_id=coder.agent_id).value)

# 3. A person approves.
print("alice approves:", guard.approve(first.approval_id, approver_id="alice").value)

# 4. A *different* call does not ride on that approval (exact-call binding).
other = ToolCall(tool="ops.deploy", args={"env": "prod", "version": "1.4.2"})
print("prod deploy:", guard.authorize(coder, other).effect.value)

# 5. The identical call is allowed once...
retry = guard.authorize(coder, deploy)
print("retry     :", retry.effect.value, "| source:", retry.source)
# 6. ...and only once (the approval was consumed).
again = guard.authorize(coder, deploy)
print("again     :", again.effect.value, "| new request:", again.approval_id != first.approval_id)

# 7. Expiry: a policy with a 1-second approval window.
short = pathlib.Path("team-short.yaml")
short.write_text(
    pathlib.Path("team.yaml").read_text().replace("ttl_seconds: 600", "ttl_seconds: 1")
)
quick = Guard.from_file(short, key=KEY)
boss = quick.start_run("planner")
dev, _ = quick.delegate(boss, "coder", tools=["ops.*"])
pending = quick.authorize(dev, deploy)
time.sleep(1.2)
print("after expiry:", quick.approve(pending.approval_id, approver_id="alice").value)

# 8. Approving from another process: the CLI shares the SQLite state file.
deploy2 = ToolCall(tool="ops.deploy", args={"env": "staging", "version": "1.5.0"})
waiting = guard.authorize(coder, deploy2)
done = subprocess.run(
    [
        "castellan",
        "approve",
        "accept",
        waiting.approval_id,
        "--state",
        "approvals-state.db",
        "--approver",
        "alice",
    ],
    capture_output=True,
    text=True,
    check=False,
)
print("cli says  :", done.stdout.strip().split(": ")[1], "| exit", done.returncode)
print("after cli :", guard.authorize(coder, deploy2).effect.value)
