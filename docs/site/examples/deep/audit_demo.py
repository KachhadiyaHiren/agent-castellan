"""Write a few decisions to an audit log (path comes from team.yaml: ./castellan-audit.jsonl)."""

from agent_castellan import Guard, ToolCall

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner", on_behalf_of="alice")
researcher, _ = guard.delegate(planner, "researcher", tools=["web.*", "fs.read"])

calls = [
    ("web.search", {"q": "castles"}),
    ("fs.read", {"path": "/workspace/notes.md"}),
    ("fs.read", {"path": "/workspace/.env"}),
    ("fs.write", {"path": "/workspace/notes.md", "content": "hi"}),
]
for tool, args in calls:
    d = guard.authorize(researcher, ToolCall(tool=tool, args=args))
    print(f"{tool:10} -> {d.effect.value}")
