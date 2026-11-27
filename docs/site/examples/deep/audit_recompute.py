"""Recompute an entry's hash by hand to see exactly what the chain covers."""

import hashlib
import json

with open("castellan-audit.jsonl") as handle:
    line = handle.readline()
entry = json.loads(line)
stored = entry.pop("hash")
body = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
recomputed = hashlib.sha256((entry["prev_hash"] + body).encode()).hexdigest()
print("stored    :", stored)
print("recomputed:", recomputed)
print("match     :", stored == recomputed)
