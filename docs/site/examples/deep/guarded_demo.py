"""@guarded: authorize plain Python functions before they run."""

from agent_castellan import ApprovalRequired, Guard, PermissionDenied
from agent_castellan.integrations.decorator import guard_context, guarded

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))


@guarded(guard, tool="fs.read")
def read_file(path: str) -> str:
    return f"<contents of {path}>"


@guarded(guard, tool="fs.write")
def write_file(path: str, content: str) -> None:
    print("wrote", path)


planner = guard.start_run("planner")
coder, _ = guard.delegate(planner, "coder", tools=["fs.*"])

try:
    read_file("/workspace/a.txt")  # no context yet: fails closed
except Exception as exc:
    print(type(exc).__name__, "-", exc)

with guard_context(coder, guard._chains[coder.agent_id]):
    print(read_file("/workspace/a.txt"))
    try:
        read_file("/workspace/.env")
    except PermissionDenied as exc:
        print("PermissionDenied -", exc)
    try:
        write_file("/workspace/a.txt", "hello")
    except ApprovalRequired as exc:
        print("ApprovalRequired -", exc.approval_id[:5] + "...")
