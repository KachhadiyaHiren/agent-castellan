"""guard_tools: wrap LangChain/LangGraph tools so every call is authorized."""

from langchain_core.tools import tool

from agent_castellan import Guard
from agent_castellan.integrations.langgraph import guard_tools

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))
planner = guard.start_run("planner")
researcher, _ = guard.delegate(planner, "researcher", tools=["web.*", "fs.read"])


@tool
def web_search(q: str) -> str:
    """Search the web."""
    return f"results for {q}"


@tool
def fs_read(path: str) -> str:
    """Read a file."""
    return f"<contents of {path}>"


# Policy tool names are dotted (web.search), so give the tools those names.
web_search.name, fs_read.name = "web.search", "fs.read"

safe = guard_tools([web_search, fs_read], guard, lambda: researcher, on_denied="message")
by_name = {t.name: t for t in safe}
print(by_name["web.search"].invoke({"q": "castles"}))
print(by_name["fs.read"].invoke({"path": "/workspace/notes.md"}))
print(by_name["fs.read"].invoke({"path": "/workspace/.env"}))
