import secrets

from agent_castellan import Guard, PermissionDenied, ToolCall

guard = Guard.from_file("team.yaml", key=secrets.token_bytes(32))
planner = guard.start_run("planner", on_behalf_of="alice")

researcher, _ = guard.delegate(planner, "researcher", tools=["web.*"], ttl_seconds=600)
coder, _ = guard.delegate(planner, "coder", tools=["fs.*"], ttl_seconds=600)


def show(who, name, tool, **args):
    d = guard.authorize(who, ToolCall(tool=tool, args=args))
    print(f"{name:10} {tool:12} -> {d.effect.value:5} rule={d.rule_id} source={d.source}")


show(researcher, "researcher", "web.search", query="castellan")
show(researcher, "researcher", "fs.read", path="/workspace/notes.md")
show(coder, "coder", "fs.read", path="/workspace/.env")
show(coder, "coder", "fs.write", path="/workspace/app.py", content="x")
show(coder, "coder", "web.search", query="castellan")

try:
    guard.delegate(researcher, "coder", tools=["fs.read"], ttl_seconds=60)
except PermissionDenied as exc:
    print("researcher cannot delegate:", exc)
