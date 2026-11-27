"""Process A (the planner): delegate, then print what the worker needs as one JSON line."""

import json

from agent_castellan import Guard
from agent_castellan.delegation.grants import chain_to_token

guard = Guard.from_file("team.yaml", key=bytes.fromhex("11" * 32))  # same key as process B
planner = guard.start_run("planner", on_behalf_of="alice")
worker, _ = guard.delegate(planner, "researcher", tools=["web.*"], max_calls=5)
handoff = {
    "principal": worker.model_dump(),
    "chain": chain_to_token(guard._chains[worker.agent_id]),
}
print(json.dumps(handoff))
