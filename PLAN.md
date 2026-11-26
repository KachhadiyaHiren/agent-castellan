# Castellan — Implementation Plan

> **Castellan** (noun): the keeper of a castle, who decides who may enter and what they may do.

**One line:** A permission layer for multi-agent AI systems. You write YAML rules that **allow**, **deny**, or **require approval** for every tool call. When one agent hands work to another, the second agent can never get more power than the first.

| | |
|---|---|
| PyPI distribution | `agent-castellan` (free on PyPI as of 2026-11-27) |
| Import name | `agent_castellan` |
| CLI | `castellan` |
| Repo | `github.com/KachhadiyaHiren/agent-castellan` |
| License | Apache-2.0 (patent grant; preferred by companies adopting security tooling) |
| Python | 3.11, 3.12, 3.13 |

---

## 0. How to use this document

This plan is written so that **several coding sessions can work at the same time without stepping on each other**. The rules:

1. **Phase 0 runs alone, first.** It creates every shared file: models, interfaces, stubs, `pyproject.toml`, CI. After Phase 0 is merged, shared files are **frozen**.
2. **Each workstream (WS) owns a disjoint set of files.** A session may only create or edit files listed under its "Owns" section. If it believes a shared file must change, it stops and reports instead of editing.
3. **Every session works on its own branch in its own worktree**, starting from `main` after the previous phase is merged.
4. **Each brief in §9 is copy-paste ready.** It names the section of this plan to read, the files owned, the acceptance commands, and the report format.
5. **Done means:** all acceptance commands pass locally, the branch is pushed, and the session returns the report in §8.4.

---

## 1. Why this project (and how it differs)

Several small YAML "tool-call gate" libraries exist (agent-action-gate, toolpolicy, agent-policy/guard, Cohorte guardrails, agent-authz). **All of them treat agents as one flat identity.** Real systems are now multi-agent: a planner hands work to a researcher, which hands work to a browser agent. That creates problems none of them solve:

| Problem in multi-agent systems | Castellan's answer |
|---|---|
| A sub-agent ends up with more power than the agent that created it | **Delegation grants with attenuation**: a child's power is always ≤ its parent's. Enforced with chained HMAC "caveats" (macaroon-style), so a grant cannot be widened, even by code that holds it. |
| One runaway sub-agent burns the whole budget | **Run-tree budgets**: limits on tool calls (and optional cost units) that are shared across the whole agent tree, plus per-agent limits. |
| "Ask a human" doesn't scale | **Approval routing**: an `ask` rule can be routed to a human or to a supervisor agent role. Approvals are bound to the exact call (hash of tool + canonical args), single-use, and expire. |
| Nobody can tell afterwards which agent did what, on whose behalf | **Tamper-evident audit log**: append-only JSONL where each entry carries the hash of the previous one. `castellan audit verify` detects edits and deletions. |
| Policies grow until nobody trusts them | **Policy tooling like real software**: `castellan test` (unit tests for policies), `castellan explain` (why a decision happened), `castellan lint` (shadowed rules, unreachable rules, overly broad allows). |
| Every framework needs its own integration | **MCP proxy**: sits between any MCP client and any MCP server and enforces policy on `tools/call`. Works with every MCP-capable agent without code changes. Plus a Python `Guard` API and a LangGraph adapter. |

**Resume summary** (for later): *"Designed and built Castellan, an open-source authorization layer for multi-agent LLM systems: a YAML policy language with a safe condition DSL, macaroon-style delegation with provable attenuation, tamper-evident audit logging, an MCP enforcement proxy, and policy static analysis. Sub-50µs decisions, property-tested security invariants."*

---

## 2. Core concepts

```
             user (root principal, "on behalf of")
                  │
            ┌─────▼─────┐   delegate(tools=[fs.*, web.search], ttl=10m, max_calls=40)
            │  planner  │──────────────────────────────┐
            └─────┬─────┘                              │
                  │ delegate(tools=[web.search])       │
            ┌─────▼──────┐                       ┌─────▼────┐
            │ researcher │                       │  coder   │
            └─────┬──────┘                       └─────┬────┘
                  │ tool call                          │ tool call: fs.write
                  ▼                                    ▼
        ┌──────────────────────────────────────────────────────────┐
        │                       Guard.authorize                    │
        │  1. budget precheck  (run tree + per agent)              │
        │  2. policy decision  (rules → allow / deny / ask)        │
        │  3. grant check      (every grant in the chain must allow)│
        │  4. approval         (if ask: pending → approved/denied) │
        │  5. audit append     (hash-chained)                      │
        │  6. budget consume   (only if finally allowed)           │
        └──────────────────────────────────────────────────────────┘
```

**Terms (use these names exactly in code and docs):**

- **Principal** — an agent identity in one run: `agent_id`, `role`, `run_id`, `parent_id`, `depth`, `on_behalf_of` (the human/user id at the root).
- **ToolCall** — the thing being authorized: `tool` (namespaced string, e.g. `fs.write`, `github.create_issue`, `mcp:filesystem/read_file`), `args` (JSON object), optional `resource` attributes.
- **Rule** — one YAML rule: `id`, match on `agents`/`tools`, optional `when` conditions, `effect` (`allow` | `deny` | `ask`), optional `reason`, `approver`, `priority`.
- **Policy** — a loaded, validated set of rules + agents config + budgets + defaults.
- **Decision** — result: `effect`, `reason`, `rule_id` (or `None` for default), `trace` (list of rules considered and why each matched or not), `approval_id` (when `ask`).
- **Grant** — a delegation from parent to child: allowed tool globs, extra conditions, `expires_at`, `max_calls`, signed by chained HMAC. A chain of grants goes from the root to the current agent.
- **Run** — one top-level task; all principals in one delegation tree share a `run_id` and a run budget.

**Decision algorithm (normative):**

1. Normalize the call (§4.6). If normalization fails → `deny` with reason `invalid_call`.
2. Collect rules whose `agents` and `tools` match and whose `when` evaluates true.
3. If any matching rule is `deny` → **deny** (deny overrides everything, regardless of priority).
4. Else if any matching rule is `ask` → **ask**.
5. Else if any matching rule is `allow` → **allow**.
6. Else → `defaults.effect` (default `deny`).
7. Within the winning effect, `rule_id` is the matching rule with the highest `priority`, then earliest in file order.
8. Final effect = most restrictive of (policy decision, grant chain result). Grant chain can only turn `allow`/`ask` into `deny`, never the reverse.

---

## 3. Policy language (YAML, version 1)

```yaml
version: 1

defaults:
  effect: deny            # deny | ask | allow  (deny recommended)

agents:                   # roles; ids are assigned at runtime
  planner:
    can_delegate_to: [researcher, coder]
    max_delegation_depth: 2
  researcher: {}
  coder: {}
  reviewer: {}

rules:
  - id: no-secrets
    description: Never touch secret files, whoever asks
    tools: ["*"]
    when:
      any:
        - args.path: { glob: "**/.env*" }
        - args.path: { glob: "**/*.pem" }
    effect: deny
    reason: Secret files are off limits

  - id: read-workspace
    agents: [researcher, coder, reviewer]
    tools: ["fs.read", "fs.list"]
    when:
      args.path: { glob: "/workspace/**" }
    effect: allow

  - id: write-needs-review
    agents: [coder]
    tools: ["fs.write", "fs.delete"]
    when:
      args.path: { glob: "/workspace/**" }
    effect: ask
    approver: role:reviewer        # human | role:<role> | agent:<id>

  - id: small-payments-only
    tools: ["payments.*"]
    when:
      all:
        - args.amount: { lte: 100 }
        - args.currency: { in: [USD, EUR] }
    effect: ask
    approver: human

  - id: shallow-web
    agents: [researcher]
    tools: ["web.search", "web.fetch"]
    when:
      agent.depth: { lte: 2 }
    effect: allow

budgets:
  run:
    max_tool_calls: 200
    max_cost_units: 500           # optional; callers pass cost per call
  per_role:
    researcher: { max_tool_calls: 80 }
    coder: { max_tool_calls: 60 }

approvals:
  ttl_seconds: 600

audit:
  path: ./castellan-audit.jsonl
```

### 3.1 Matching

- `agents`: list of role names. Omitted or `["*"]` = all roles.
- `tools`: list of glob patterns over the normalized tool name. `*` matches any characters except `.`; `**` matches anything including `.`. A bare `"*"` as the whole pattern is special-cased to match every tool. Matching runs on the normalized (lower-cased) name.

### 3.2 Condition DSL (`when`)

The `when` block is a **data-only** language. Nothing is ever passed to `eval`.

- A mapping of `path: {operator: operand}` entries means **all** must hold.
- Combinators: `all: [ ... ]`, `any: [ ... ]`, `not: { ... }`. They nest.
- Paths are dotted lookups into the evaluation context:
  - `agent.id`, `agent.role`, `agent.depth`, `agent.parent_role`, `agent.on_behalf_of`
  - `tool.name`, `tool.namespace` (part before the first `.` or `:`)
  - `args.<key>[.<key>...]` (list indexes as `args.items.0.name`)
  - `run.id`, `run.tool_calls` (calls so far in this run)
  - `time.hour_utc`, `time.weekday` (0=Mon)
- A missing path makes every operator false **except** `exists: false`.

| Operator | Operand | Meaning |
|---|---|---|
| `eq`, `ne` | any scalar | equality |
| `in`, `not_in` | list | membership |
| `lt`, `lte`, `gt`, `gte` | number | numeric compare; non-numbers → false |
| `glob` | string | path-style glob (`**` crosses `/`), applied after path normalization |
| `regex` | string | Python `re.fullmatch`; compiled at load time; max pattern length 512 |
| `contains` | scalar | substring (str) or element (list) |
| `starts_with`, `ends_with` | string | string prefix/suffix |
| `exists` | bool | path present or absent |
| `len_lte`, `len_gte` | int | length of str/list |

Unknown operator or wrong operand type → **load-time error** with file, line and rule id.

### 3.3 Approver values

`human` (default) | `role:<role>` (any active agent of that role in the same run may approve) | `agent:<agent_id>`. An agent may **never** approve its own request (enforced).

### 3.4 Policy tests file (for `castellan test`)

```yaml
# policies/tests/team.test.yaml
policy: ../team.yaml
cases:
  - name: coder cannot read secrets
    agent: { role: coder, depth: 1 }
    call: { tool: fs.read, args: { path: /workspace/.env } }
    expect: deny
    expect_rule: no-secrets
  - name: coder write needs approval
    agent: { role: coder, depth: 1 }
    call: { tool: fs.write, args: { path: /workspace/app.py, content: "x" } }
    expect: ask
```

---

## 4. Architecture and code layout

### 4.1 Tech stack (fixed, do not change)

| Concern | Choice |
|---|---|
| Packaging / env | `uv`, build backend `hatchling`, `src/` layout |
| Models | `pydantic` v2 (frozen models for value types) |
| YAML | `ruamel.yaml` (keeps line numbers for error messages) |
| CLI | `typer` + `rich` |
| MCP | official `mcp` Python SDK |
| Storage | in-memory default; SQLite (stdlib `sqlite3`) for approvals/budgets when a path is configured |
| Crypto | stdlib `hmac` + `hashlib` (SHA-256); `secrets` for keys |
| Tests | `pytest`, `pytest-cov`, `pytest-xdist`, `hypothesis`, `pytest-benchmark` |
| Lint / types | `ruff` (lint + format), `mypy --strict` |
| Docs | `mkdocs-material` |

**Runtime dependencies are only:** `pydantic`, `ruamel.yaml`, `typer`, `rich`. Extras: `[mcp]` → `mcp`; `[langgraph]` → `langgraph`. Keep the core install small.

### 4.2 Repository layout and ownership

```
agent-castellan/
├── pyproject.toml                    P0 (frozen after Phase 0)
├── README.md                         P0 stub → WS7 final
├── LICENSE, SECURITY.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md   P0
├── CHANGELOG.md                      P0 (each WS appends one line under "Unreleased")
├── PLAN.md                           this file
├── docs/
│   ├── CONVENTIONS.md                P0
│   └── site/…                        WS7
├── .github/workflows/ci.yml          P0
├── .github/workflows/release.yml     WS9
├── src/agent_castellan/
│   ├── __init__.py                   P0  (public API re-exports, frozen)
│   ├── py.typed                      P0
│   ├── models.py                     P0  Principal, ToolCall, Decision, Effect, Grant, …  (frozen)
│   ├── interfaces.py                 P0  Protocols for every component (frozen)
│   ├── errors.py                     P0  exception hierarchy (frozen)
│   ├── guard.py                      P0  Guard orchestration (calls interfaces only)
│   ├── policy/                       WS1
│   │   ├── loader.py                 YAML → Policy, errors with line numbers
│   │   ├── schema.py                 pydantic models for the YAML document
│   │   ├── conditions.py             condition DSL compiler + evaluator
│   │   ├── matching.py               tool-glob + agent matching
│   │   ├── normalize.py              call normalization (§4.6)
│   │   └── engine.py                 PolicyEngine (implements interfaces.PolicyDecider)
│   ├── delegation/                   WS2
│   │   ├── grants.py                 Grant minting, attenuation, serialization
│   │   ├── chain.py                  chain verification (implements interfaces.GrantVerifier)
│   │   └── keys.py                   key management (root key, rotation)
│   ├── runtime/                      WS3
│   │   ├── approvals.py              ApprovalStore memory + sqlite (implements interfaces.ApprovalStore)
│   │   └── budgets.py                BudgetTracker memory + sqlite (implements interfaces.BudgetTracker)
│   ├── audit/                        WS4
│   │   ├── log.py                    hash-chained JSONL writer (implements interfaces.AuditSink)
│   │   └── verify.py                 chain verification
│   ├── analysis/                     WS4
│   │   └── lint.py                   static checks on a Policy
│   ├── cli/                          WS4  (one module per command group)
│   │   ├── __init__.py  app.py  check.py  explain.py  test.py  lint.py  audit.py  approve.py
│   ├── integrations/                 WS5
│   │   ├── decorator.py              @guarded for plain Python tools
│   │   ├── mcp_proxy.py              stdio MCP proxy enforcing policy
│   │   └── langgraph.py              ToolNode wrapper
│   └── testing/                      P0
│       └── fakes.py                  in-memory fakes of every interface (for isolated WS tests)
├── tests/
│   ├── unit/policy/ …                WS1
│   ├── unit/delegation/ …            WS2
│   ├── unit/runtime/ …               WS3
│   ├── unit/audit/ unit/analysis/ unit/cli/   WS4
│   ├── unit/integrations/ …          WS5
│   ├── unit/test_guard.py            P0
│   ├── property/ …                   WS8
│   ├── integration/ …                WS8 (wires real components together)
│   └── bench/ …                      WS7
├── examples/
│   ├── policies/                     WS7 (cookbook)
│   └── multi_agent_team/             WS6
└── benchmarks/                       WS7
```

### 4.3 Public models (`models.py`, written in Phase 0)

```python
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class Effect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent_id: str
    role: str
    run_id: str
    parent_id: str | None = None
    parent_role: str | None = None
    depth: int = 0  # root agent = 0
    on_behalf_of: str | None = None  # end-user id


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    cost_units: float = 0.0


class TraceStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    matched: bool
    detail: str  # e.g. "tools: no match for 'fs.write'"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)
    effect: Effect
    reason: str
    rule_id: str | None = None
    source: str = "policy"  # policy | grant | budget | approval | default | invalid
    trace: tuple[TraceStep, ...] = ()
    approval_id: str | None = None


class Grant(BaseModel):
    model_config = ConfigDict(frozen=True)
    grant_id: str
    issuer_agent_id: str
    subject_agent_id: str
    subject_role: str
    run_id: str
    tools: tuple[str, ...]  # globs, must be ⊆ issuer's effective tools
    when: dict[str, Any] | None = None  # extra conditions, same DSL as rules
    expires_at: datetime
    max_calls: int | None = None
    signature: str  # hex HMAC, chained (see §5.2)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    approval_id: str
    principal: Principal
    call: ToolCall
    call_hash: str
    approver: str
    rule_id: str
    created_at: datetime
    expires_at: datetime


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    seq: int
    at: datetime
    principal: Principal
    call: ToolCall
    decision: Decision
    prev_hash: str
    hash: str
```

### 4.4 Interfaces (`interfaces.py`, written in Phase 0)

```python
from typing import Protocol, Sequence
from .models import (
    Principal,
    ToolCall,
    Decision,
    Grant,
    ApprovalRequest,
    ApprovalStatus,
    AuditEntry,
)


class PolicyDecider(Protocol):
    def decide(self, principal: Principal, call: ToolCall) -> Decision: ...
    def approver_for(self, rule_id: str) -> str: ...
    def can_delegate(self, parent_role: str, child_role: str, depth: int) -> bool: ...


class GrantVerifier(Protocol):
    def verify(
        self, chain: Sequence[Grant], principal: Principal, call: ToolCall
    ) -> Decision: ...  # ALLOW or DENY only
    def mint(
        self,
        parent: Principal,
        parent_chain: Sequence[Grant],
        child: Principal,
        tools: Sequence[str],
        when: dict | None,
        ttl_seconds: int,
        max_calls: int | None,
    ) -> Grant: ...


class ApprovalStore(Protocol):
    def create(
        self, principal: Principal, call: ToolCall, rule_id: str, approver: str, ttl_seconds: int
    ) -> ApprovalRequest: ...
    def resolve(self, approval_id: str, approver_id: str, approve: bool) -> ApprovalStatus: ...
    def consume(self, principal: Principal, call: ToolCall) -> bool:
        ...
        # True once if an APPROVED, unexpired request matches this exact call_hash

    def pending(self, run_id: str | None = None) -> list[ApprovalRequest]: ...


class BudgetTracker(Protocol):
    def precheck(self, principal: Principal, call: ToolCall) -> Decision | None:
        ...
        # None = within budget; Decision(DENY, source="budget") otherwise

    def consume(self, principal: Principal, call: ToolCall) -> None: ...
    def usage(self, run_id: str) -> dict[str, float]: ...


class AuditSink(Protocol):
    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry: ...


class Clock(Protocol):
    def now(self) -> "datetime": ...
```

### 4.5 `Guard` (written in Phase 0; the only entry point users need)

```python
class Guard:
    def __init__(
        self,
        decider: PolicyDecider,
        grants: GrantVerifier,
        approvals: ApprovalStore,
        budgets: BudgetTracker,
        audit: AuditSink,
        clock: Clock,
        approval_ttl: int = 600,
    ) -> None: ...

    @classmethod
    def from_file(
        cls,
        policy_path: str | Path,
        *,
        key: bytes | None = None,
        state_path: str | Path | None = None,
    ) -> "Guard":
        ...
        # wires the real components (imports done lazily so Phase 0 tests use fakes)

    def start_run(self, role: str, *, on_behalf_of: str | None = None) -> Principal: ...
    def delegate(
        self,
        parent: Principal,
        child_role: str,
        *,
        tools: Sequence[str],
        when: dict | None = None,
        ttl_seconds: int = 900,
        max_calls: int | None = None,
    ) -> tuple[Principal, Grant]: ...
    def authorize(
        self, principal: Principal, call: ToolCall, *, chain: Sequence[Grant] = ()
    ) -> Decision: ...  # full pipeline §2
    def check(
        self, principal: Principal, call: ToolCall, *, chain: Sequence[Grant] = ()
    ) -> Decision: ...  # dry run: no audit, no budget, no approval creation
    def approve(
        self, approval_id: str, *, approver_id: str, approve: bool = True
    ) -> ApprovalStatus: ...
```

`authorize` behaviour for `ask`: if `approvals.consume(...)` returns True → treat as ALLOW with `source="approval"`. Otherwise create a request and return `Decision(effect=ASK, approval_id=…)`. The caller retries the same call after approval.

### 4.6 Call normalization (WS1, `policy/normalize.py`)

Security-critical. Done **before** any matching, and the normalized call is what gets audited.

- Tool name: strip, lower-case, reject empty or control characters, collapse `mcp:server/tool` into namespace `mcp:server` + name.
- Any arg whose key is in `{path, file, filename, filepath, dir, directory, cwd, target, source, dest, destination}` or ends with `_path`: resolve `.` / `..` **lexically** (`posixpath.normpath`), reject NUL bytes, Unicode-normalize (NFC). A path that escapes above `/` after normalization → invalid.
- URLs (keys `url`, `uri`, `endpoint`, or ending `_url`): parse, lower-case scheme and host, drop default ports, punycode IDNs.
- Args must be JSON-serializable; depth ≤ 32; total size ≤ 1 MiB.
- `call_hash` = SHA-256 of canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) of `{tool, args}` after normalization.

---

## 5. Component specifications

### 5.1 WS1 — Policy engine
- Loader produces errors like `team.yaml:42 rule 'write-needs-review': unknown operator 'lessthan'`.
- Conditions compile once to closures at load time; evaluation does no parsing.
- `PolicyEngine.decide` must follow §2 exactly and fill `trace` (one step per rule considered, cheap strings).
- Budget: **p50 < 20µs, p99 < 100µs** for a 50-rule policy on a laptop (WS7 measures; WS1 should keep this in mind: precompute tool-glob regexes, index rules by tool namespace).
- `can_delegate(parent_role, child_role, depth)` uses `agents.<role>.can_delegate_to` and `max_delegation_depth`.

### 5.2 WS2 — Delegation (macaroon-style)
- Root key: 32 random bytes (from `key=` arg, env `CASTELLAN_KEY` as hex, or generated per process with a warning).
- Signature chain: `sig_0 = HMAC(root_key, canonical(grant_0 without signature))`; `sig_n = HMAC(sig_{n-1}, canonical(grant_n without signature))`. Verifying requires the root key and the whole chain; a holder of a grant can add a narrower child grant but cannot alter or widen any earlier one.
- **Attenuation rule (must hold, property-tested by WS8):** for every grant n>0, every tool glob in `grant_n.tools` must be covered by some glob in `grant_{n-1}.tools` (implement `glob_subsumes(a, b)` conservatively: if unsure, reject), `expires_at_n ≤ expires_at_{n-1}`, `max_calls_n ≤ max_calls_{n-1}` when the parent sets one, and `when_n` is AND-ed with all ancestors' `when`.
- `verify` checks: signatures, chain links (`subject` of n-1 is `issuer` of n), last subject is the principal, run ids equal, not expired (via `Clock`), tool covered by every grant, every `when` true (use WS1's condition evaluator through `agent_castellan.policy.conditions.compile_condition` — that function signature is fixed in Phase 0 as a stub). `max_calls` per grant is counted by WS3's budget tracker, not here.
- Serialization: `Grant.to_token()` → compact base64url JSON; `Grant.from_token()`; chains as `token1.token2.…` so they can be passed between processes/agents.

### 5.3 WS3 — Approvals and budgets
- Approvals: request bound to `call_hash`; status transitions `PENDING → APPROVED|DENIED|EXPIRED`, `APPROVED → CONSUMED` (exactly once). Self-approval forbidden. `role:<r>` approver: `approver_id` must be an agent of role r in the same run (Guard passes a Principal-like check; store keeps `approver` string and the resolver's role).
- Budgets: counters keyed by `run_id`, `(run_id, role)`, `(run_id, agent_id)`, `(run_id, grant_id)`. Thread-safe (`threading.Lock`); SQLite backend uses `BEGIN IMMEDIATE` transactions for atomic check-and-increment across processes.
- Both have `memory` and `sqlite` implementations sharing one test suite (parametrized fixture).

### 5.4 WS4 — Audit, analysis, CLI
- Audit line = canonical JSON of `AuditEntry`; `hash = sha256(prev_hash + canonical(entry without hash))`; genesis `prev_hash = "0"*64`. Writes are `O_APPEND` + `flush` + `fsync` (configurable `fsync=False` for speed). File lock (`fcntl` on POSIX) for multi-process writers.
- `verify` returns first bad seq and why (`hash_mismatch`, `gap`, `reordered`).
- Lint checks (each has an id, severity, message, rule id, line):
  - `L001` shadowed allow: an `allow` rule fully covered by an earlier `deny` with no `when` → never effective.
  - `L002` duplicate rule ids.
  - `L003` wildcard allow: `tools: ["*"]` with effect `allow` and no `when`.
  - `L004` role referenced in rules/approver but not defined in `agents`.
  - `L005` `ask` rule whose approver role cannot exist in a run (no role delegates to it and it isn't a root).
  - `L006` unreachable delegation: role never reachable from any `can_delegate_to`.
  - `L007` `defaults.effect: allow` (warning).
- CLI commands:
  - `castellan check POLICY --role R --tool T --args JSON [--depth N]` → prints decision, exit 0 allow / 1 deny / 2 ask.
  - `castellan explain …same args…` → rich table of the trace.
  - `castellan test TESTFILE…` → pytest-like output, exit non-zero on failure, `--junit out.xml`.
  - `castellan lint POLICY [--format text|json|github]` (`github` = workflow annotation format).
  - `castellan audit verify FILE` / `castellan audit tail FILE [--run ID]`.
  - `castellan approve list|accept|reject --state PATH` (sqlite state).
  - `castellan mcp-proxy` is registered by WS5 in `cli/app.py`? **No** — WS5 owns `integrations/mcp_proxy.py` which exposes `register(app: typer.Typer)`; Phase 0 already calls it lazily from `cli/app.py` inside a try/except ImportError for the `[mcp]` extra.

### 5.5 WS5 — Integrations
- `@guarded(guard, tool="fs.write")` decorator: builds `ToolCall` from the function's bound arguments, reads principal + chain from a `contextvars` context (`with guard_context(principal, chain): …`), raises `PermissionDenied` (deny) or `ApprovalRequired(approval_id)` (ask).
- MCP proxy: `castellan mcp-proxy --policy team.yaml --role coder -- <server command…>`. Starts the real server as a subprocess over stdio, relays all JSON-RPC messages, intercepts `tools/call` → `Guard.authorize` with tool name `mcp:<server-name>/<tool>`. Deny → returns a tool result with `isError: true` and the reason text (not a protocol error, so the agent can adapt). Ask → `isError: true` with "approval required: <id>; run `castellan approve accept <id>`". Also filters `tools/list` to hide tools the role can never use (optional flag `--hide-denied`).
- LangGraph: `guard_tools(tools, guard, principal_getter)` returns wrapped tools; documented with a 30-line example.

### 5.6 WS6 — Multi-agent reference team (`examples/multi_agent_team/`)
A small but real multi-agent app that shows every feature. It is the demo in the README and the GIF.
- Agents: **planner** (splits the task, delegates), **researcher** (web.search / web.fetch, read-only), **coder** (fs.read / fs.write in a temp workspace), **reviewer** (approves or rejects coder writes as `role:reviewer` approver).
- Tools are local and safe: `fs.*` on a temp dir, `web.search` returns canned results from a fixture file.
- LLM layer behind a tiny `ChatModel` protocol with two implementations: `ScriptedModel` (deterministic, used in tests and CI) and `OpenAICompatibleModel` (any OpenAI-compatible HTTP endpoint via `httpx`; configured by env `CASTELLAN_EXAMPLE_BASE_URL`, `CASTELLAN_EXAMPLE_MODEL`, `CASTELLAN_EXAMPLE_API_KEY`). No vendor SDKs.
- Scenarios (each a test): happy path; coder tries to read `.env` → denied and adapts; researcher tries to delegate further → blocked by depth; runaway researcher hits per-role budget; coder write → reviewer approves → retry succeeds; tampered grant token → rejected.
- `python -m examples.multi_agent_team --scripted` prints a colourful timeline (rich) of agents, calls and decisions.

### 5.7 WS7 — Docs, cookbook, benchmarks
- mkdocs-material site: Getting started (5 minutes), Concepts, Policy language reference (generated tables from WS1 operator registry), Multi-agent delegation, Approvals, Audit, MCP proxy, LangGraph, CLI reference (generated from typer), Security model & threat model, FAQ.
- Cookbook (`examples/policies/`, each with a test file): read-only research agent, coding agent in a sandbox dir, payments with approval, GitHub agent (no force-push, no deleting repos), database agent (SELECT only via regex), customer-support agent (PII redaction note), office-hours only (`time.hour_utc`), two-person rule (approval by `role:lead`), staging vs prod by `args.env`, multi-agent research team.
- Benchmarks: `pytest-benchmark` for decide (10/50/500 rules), verify chain (depth 1/3/5), audit append (fsync on/off). Publish a table in docs.
- README: problem, 20-line quickstart, multi-agent diagram, feature table, comparison table (honest, linking the other projects), badges.

### 5.8 WS8 — Hardening (property tests, integration, threat review)
- Hypothesis properties:
  - Attenuation: for random grant chains, any call allowed by the child chain is allowed by every prefix.
  - Deny overrides: adding a matching deny rule never turns deny into allow.
  - Normalization idempotence: `normalize(normalize(x)) == normalize(x)`; `../` tricks never escape a glob like `/workspace/**`.
  - Audit: any single-byte change in a log file is detected by `verify`.
  - Condition DSL: random documents either load or raise `PolicyError` (never another exception).
- Integration tests: real components wired through `Guard.from_file` with the cookbook policies.
- `docs/site/security.md` threat model: what Castellan protects against (over-privileged sub-agents, prompt-injected tool calls, approval replay, log tampering) and what it does **not** (a malicious host process that bypasses the guard, tools that ignore the decision).

### 5.9 WS9 — Release
- `release.yml`: on tag `v*` → build with `uv build` → publish with PyPI **trusted publishing** (no token in repo) → GitHub release with changelog section.
- Version `0.1.0`. Docs deployed to GitHub Pages.

---

## 6. Phases, workstreams and order

| Phase | Workstreams (parallel within a phase) | Starts after |
|---|---|---|
| **0 Foundation** | P0 (single session) | — |
| **1 Core** | WS1 policy · WS2 delegation · WS3 approvals+budgets · WS4 audit+lint+CLI · WS5 integrations | Phase 0 merged |
| **2 Showcase & hardening** | WS6 multi-agent team · WS7 docs+cookbook+bench · WS8 hardening | Phase 1 merged |
| **3 Release** | WS9 (single session) | Phase 2 merged |

**Why Phase 1 can run fully in parallel:** each WS codes against `interfaces.py` and tests with `testing/fakes.py`. WS2 needs the condition compiler from WS1: Phase 0 ships `policy/conditions.py` with the **final signature** and a minimal working implementation for `eq`/`in`/`glob`, and WS1 replaces the body. WS2 tests use only those three operators.

**Merge order inside Phase 1** (reduces surprises): WS1 → WS2 → WS3 → WS4 → WS5. After each merge, the next branch rebases on `main` and re-runs the full suite before merging.

---

## 7. Phase 0 — Foundation (detailed checklist)

1. `git init`, default branch `main`. Local identity:
   `git config user.name "Hiren Kachhadiya"` and
   `git config user.email "122442853+KachhadiyaHiren@users.noreply.github.com"`.
2. `uv init --lib --package` adjusted to the layout in §4.2; `pyproject.toml` with:
   - `[project]` metadata, Apache-2.0, classifiers, `requires-python = ">=3.11"`, URLs.
   - deps & extras exactly as §4.1; `[dependency-groups] dev = [...]`.
   - `[project.scripts] castellan = "agent_castellan.cli.app:main"`.
   - ruff config: `line-length = 100`, `select = ["E","F","W","I","B","UP","SIM","RUF","N","S","PT","PL"]` with sensible ignores (`PLR0913`, `S101` in tests).
   - mypy: `strict = true`, `plugins = ["pydantic.mypy"]`.
   - pytest: `addopts = "-q --strict-markers --cov=agent_castellan --cov-report=term-missing --cov-fail-under=90"`, `testpaths = ["tests"]`.
3. Write `models.py`, `interfaces.py`, `errors.py` (`CastellanError` → `PolicyError`, `GrantError`, `PermissionDenied`, `ApprovalRequired`, `BudgetExceeded`) exactly as §4.3/§4.4.
4. Write `guard.py` fully (orchestration only) + `testing/fakes.py` (dict-backed fakes of all five interfaces + `FrozenClock`).
5. Create every module in §4.2 as a stub with the class/function signatures and `raise NotImplementedError` — **except** `policy/conditions.py` (minimal `eq`/`in`/`glob`) so WS2 can start.
6. `cli/app.py` with the typer app and lazy registration of each command module (missing implementation → command prints "not implemented yet").
7. `tests/unit/test_guard.py`: full pipeline tests using fakes (allow, deny, ask→approve→retry, budget deny, grant deny overrides allow, audit called once per authorize, check() has no side effects).
8. CI `ci.yml`: matrix {ubuntu, macos} × {3.11, 3.12, 3.13}: `uv sync --all-extras`, `ruff check`, `ruff format --check`, `mypy src`, `pytest -n auto`. Coverage threshold temporarily enforced only on `models.py`, `guard.py`, `testing/` via a P0-only config; Phase 1 WSs keep their own packages ≥ 90%.
9. `docs/CONVENTIONS.md` (content = §8 of this plan), `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `CHANGELOG.md` (Keep a Changelog), `.gitignore`, `.editorconfig`, `pre-commit` config (ruff).
10. `README.md` stub (name, one-liner, "under construction").
11. Commit, create the GitHub repo, push `main`. Branch protection: require CI green.

**Phase 0 acceptance:** `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` all pass; `uv run castellan --help` lists all commands.

---

## 8. Conventions for every session

### 8.1 Code
- Type hints everywhere; `mypy --strict` clean. No `Any` in public signatures except `args`/`resource` dicts.
- Public functions and classes get a one-line docstring saying what, not how.
- No global mutable state. Time only via `Clock`; randomness only via `secrets`/injected generators.
- Errors: raise subclasses from `errors.py`; messages state what was wrong and where.
- No network access in library code (except WS6 `OpenAICompatibleModel`). No network in tests.

### 8.2 Tests
- Write the test first for each behaviour in your section. Name tests by behaviour: `test_deny_rule_overrides_higher_priority_allow`.
- Each WS keeps its package at **≥ 90% line coverage and ≥ 85% branch coverage**.
- Use `testing/fakes.py` for other components; never import another WS's implementation in Phase 1 unit tests.
- Fast: the whole suite under 30s on a laptop. Mark anything slower `@pytest.mark.slow`.

### 8.3 Git
- Branch: `ws<N>-<short-name>` (e.g. `ws2-delegation`).
- Conventional Commits: `feat(policy): add regex operator`, `test(delegation): …`, `docs: …`. Small commits, each green.
- Commit messages describe the change only. **No co-author trailers, no tool or assistant names, no "generated by" lines, anywhere in commits, code, comments or docs.**
- Never edit frozen files (`pyproject.toml`, `models.py`, `interfaces.py`, `errors.py`, `__init__.py`, `guard.py`, CI) or files owned by another WS. If needed, stop and report.
- Add exactly one line to `CHANGELOG.md` under `Unreleased`.

### 8.4 Report format (every session returns this)

```
WS<N> <name> — DONE | BLOCKED
Branch: ws<N>-<name> (pushed: yes/no)  Commits: <n>
Acceptance: ruff ✔ format ✔ mypy ✔ pytest ✔ (coverage <pkg>: xx% line / yy% branch)
What was built: <3–6 bullets>
Deviations from PLAN.md: <none | list with reason>
Requests for frozen/shared files: <none | exact change + why>
Known gaps / follow-ups: <none | list>
```

---

## 9. Session briefs (copy-paste)

Each brief assumes the session starts in a fresh worktree of `agent-castellan` on a new branch from up-to-date `main`.

### P0 — Foundation
> You are building Phase 0 of the `agent-castellan` project. Read `PLAN.md` fully, then implement §7 exactly, using the models and interfaces in §4.3–§4.5 verbatim. Follow §8. Work on branch `p0-foundation`. Do not implement any WS feature beyond the stubs described. When the Phase 0 acceptance commands pass, commit, and report in the §8.4 format.

### WS1 — Policy engine
> Implement WS1 of `agent-castellan`. Read `PLAN.md` §2, §3, §4.6, §5.1 and §8. You own only `src/agent_castellan/policy/**` and `tests/unit/policy/**` (plus one CHANGELOG line). Replace the stubs with a complete implementation: loader with line-numbered errors, schema, every operator in §3.2 including combinators, tool/agent matching per §3.1, normalization per §4.6, and `PolicyEngine` implementing `PolicyDecider` with the exact decision algorithm in §2 and a full trace. Keep `compile_condition`'s signature unchanged. Write table-driven tests for every operator and every step of the decision algorithm, plus normalization attack cases (`..`, NUL, mixed case tool names, unicode). Branch `ws1-policy`. Acceptance: ruff, ruff format --check, mypy src, pytest with ≥90% line coverage on `agent_castellan.policy`. Report in §8.4 format.

### WS2 — Delegation
> Implement WS2 of `agent-castellan`. Read `PLAN.md` §2, §4.3–§4.5, §5.2 and §8. You own only `src/agent_castellan/delegation/**` and `tests/unit/delegation/**`. Implement grant minting with chained HMAC signatures, conservative `glob_subsumes`, attenuation checks at mint time (raise `GrantError`) and at verify time, token serialization, and `ChainVerifier` implementing `GrantVerifier`. Use `agent_castellan.policy.conditions.compile_condition` for `when` (only `eq`/`in`/`glob` are guaranteed during Phase 1). Test: tampering any field of any grant fails, widening tools fails, extending expiry fails, wrong root key fails, broken link fails, expired fails (use `FrozenClock`), valid 5-deep chain passes. Branch `ws2-delegation`. Acceptance as WS1 for `agent_castellan.delegation`. Report in §8.4 format.

### WS3 — Approvals and budgets
> Implement WS3 of `agent-castellan`. Read `PLAN.md` §2, §4.3–§4.5, §5.3 and §8. You own only `src/agent_castellan/runtime/**` and `tests/unit/runtime/**`. Implement `MemoryApprovalStore`, `SqliteApprovalStore`, `MemoryBudgetTracker`, `SqliteBudgetTracker`. Run one shared test suite against both backends via a parametrized fixture. Include concurrency tests: 8 threads hammering `consume` never exceed limits; an approval can be consumed exactly once across threads; SQLite tracker is correct across two connections. Branch `ws3-runtime`. Acceptance as WS1 for `agent_castellan.runtime`. Report in §8.4 format.

### WS4 — Audit, lint, CLI
> Implement WS4 of `agent-castellan`. Read `PLAN.md` §3.4, §5.4 and §8. You own only `src/agent_castellan/audit/**`, `src/agent_castellan/analysis/**`, `src/agent_castellan/cli/**` (except do not remove the lazy MCP registration in `cli/app.py`), and `tests/unit/audit/**`, `tests/unit/analysis/**`, `tests/unit/cli/**`. Implement the hash-chained audit log + verify, lint checks L001–L007, and every CLI command in §5.4 with the specified exit codes. Lint and CLI may build `Policy` objects through `agent_castellan.policy.loader` — in your unit tests, construct policies via the schema models directly or mark loader-dependent tests `@pytest.mark.needs_ws1` and skip them if the loader still raises NotImplementedError. Use `typer.testing.CliRunner`. Branch `ws4-tooling`. Acceptance as WS1 for audit/analysis/cli. Report in §8.4 format.

### WS5 — Integrations
> Implement WS5 of `agent-castellan`. Read `PLAN.md` §4.5, §5.5 and §8. You own only `src/agent_castellan/integrations/**` and `tests/unit/integrations/**`. Implement the `@guarded` decorator with `guard_context`, the stdio MCP proxy (with `register(app)` for the CLI), and the LangGraph wrapper. Test the proxy end-to-end against a tiny MCP server you write inside `tests/unit/integrations/fixtures/` using the `mcp` SDK, with `Guard` built from `testing/fakes.py`: allowed call passes through unchanged, denied call returns `isError: true` with the reason, ask returns the approval id, `--hide-denied` filters `tools/list`, non-tool messages are relayed byte-for-byte. Branch `ws5-integrations`. Acceptance as WS1 for `agent_castellan.integrations`. Report in §8.4 format.

### WS6 — Multi-agent reference team
> Implement WS6 of `agent-castellan`. Read `PLAN.md` §1, §2, §5.6 and §8. You own only `examples/multi_agent_team/**` and `tests/examples/**`. Build the four-agent team, the `ChatModel` protocol with `ScriptedModel` and `OpenAICompatibleModel`, safe local tools, the policy file, and the six scenarios as tests using `Guard.from_file` (real components). Make `python -m examples.multi_agent_team --scripted` print a clear rich timeline. Branch `ws6-team`. Acceptance: ruff, mypy on `examples/`, `pytest tests/examples`. Report in §8.4 format.

### WS7 — Docs, cookbook, benchmarks
> Implement WS7 of `agent-castellan`. Read `PLAN.md` fully, then §5.7 and §8. You own only `docs/site/**`, `mkdocs.yml`, `examples/policies/**`, `tests/bench/**`, `benchmarks/**`, `README.md`. Write the docs site, the ten cookbook policies each with a passing `castellan test` file, the benchmark suite, and the final README (with the multi-agent diagram, quickstart that actually runs, honest comparison table). Every code snippet in docs must be executed by a test (`tests/bench/test_docs_snippets.py` or similar). Branch `ws7-docs`. Acceptance: `mkdocs build --strict`, `castellan test examples/policies/tests/*.yaml`, `pytest tests/bench --benchmark-disable`. Report in §8.4 format, including the benchmark numbers.

### WS8 — Hardening
> Implement WS8 of `agent-castellan`. Read `PLAN.md` fully, then §5.8 and §8. You own only `tests/property/**`, `tests/integration/**`, `docs/site/security.md`. Write the Hypothesis properties and integration tests listed. If a test exposes a bug in another package, do not fix it: add the failing test marked `xfail(strict=True, reason="BUG: …")` and list it in your report. Branch `ws8-hardening`. Acceptance: `pytest tests/property tests/integration` (xfails allowed), ruff, mypy. Report in §8.4 format with the bug list.

### WS9 — Release
> Implement WS9 of `agent-castellan`. Read `PLAN.md` §5.9 and §8. Fix nothing outside `.github/workflows/release.yml`, `CHANGELOG.md`, and version metadata. Prepare `0.1.0`: changelog section, version bump, release workflow with PyPI trusted publishing and GitHub Pages docs deploy. Do not push tags; report the exact commands for the maintainer to run. Report in §8.4 format.

---

## 10. Quality gates (CI must enforce)

| Gate | Threshold |
|---|---|
| `ruff check`, `ruff format --check` | clean |
| `mypy --strict src` | clean |
| Tests | green on 3 Python versions × 2 OSes |
| Coverage | ≥ 90% line, ≥ 85% branch overall (after Phase 1) |
| Decision latency (bench, informational) | p50 < 20µs, p99 < 100µs at 50 rules |
| Docs | `mkdocs build --strict` |
| Policy cookbook | `castellan test examples/policies/tests/*.yaml` |

---

## 11. Launch checklist (after 0.1.0)

1. README with a 30-second GIF of the multi-agent timeline (`vhs` or `asciinema`).
2. Publish to PyPI; docs on GitHub Pages.
3. Topics on the repo: `ai-agents`, `multi-agent`, `mcp`, `authorization`, `policy-as-code`, `llm-security`, `guardrails`.
4. Write one technical blog post: "Least privilege for multi-agent systems: delegation grants that can only shrink."
5. Post to relevant communities (MCP discussions, r/LocalLLaMA, Hacker News "Show HN", LangChain Discord).
6. Open 10 `good first issue`s (new lint rules, new operators, new integrations: CrewAI, AutoGen, OpenAI Agents SDK, PydanticAI) to attract outside contributors.
7. Submit a PR adding Castellan to "awesome-mcp" style lists.

## 12. Roadmap after 0.1.0
- More integrations (CrewAI, AutoGen, PydanticAI, OpenAI Agents SDK).
- HTTP sidecar mode (`castellan serve`) for non-Python agents; TypeScript client.
- Approval channels: webhook, Slack, email.
- Argument redaction obligations (`effect: allow` + `redact: [args.token]` in audit).
- Policy bundles signed and versioned; hot reload.
- OpenTelemetry spans for decisions.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Parallel sessions edit the same files | Strict ownership table §4.2; frozen shared files; report instead of edit |
| Interfaces turn out wrong mid-Phase 1 | Sessions report requested changes; maintainer makes one coordinated change on `main`; affected branches rebase |
| `glob_subsumes` subtly wrong → privilege escalation | Conservative implementation (reject when unsure) + Hypothesis attenuation property (WS8) |
| Path tricks bypass globs | Normalization before matching (§4.6) + attack-case tests (WS1) + properties (WS8) |
| Scope creep | Anything not in this plan goes to §12 Roadmap, not into 0.1.0 |
