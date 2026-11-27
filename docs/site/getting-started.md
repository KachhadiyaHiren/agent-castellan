# Getting started

*Who this page is for:* a Python developer who has never used Castellan. *After reading it* you will have installed Castellan, written a policy, checked calls from the command line, authorized calls from Python, and delegated work to a sub-agent whose power is capped.

Every command and snippet below was run, and the output shown is what it printed. Random ids and timestamps will differ on your machine.

## 1. Install

Castellan needs Python 3.11 or newer.

```bash
pip install agent-castellan
```

Check that the command line tool works:

```bash
castellan --help
```

```text
 Usage: castellan [OPTIONS] COMMAND [ARGS]...

 Least-privilege permissions for multi-agent AI systems.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ check      Dry-run one tool call against a policy and print the decision.    │
│ explain    Show every rule considered for a call and why it matched or not.  │
│ test       Run policy test files (YAML with a policy path and cases) and     │
│            report pass/fail.                                                 │
│ lint       Find shadowed, duplicate, over-broad and unreachable rules        │
│            (checks L001-L007).                                               │
│ mcp-proxy  Run an MCP server behind a policy-enforcing stdio proxy:          │
│            castellan mcp-proxy --policy team.yaml --role coder -- <server    │
│            command...>                                                       │
│ audit      Verify and tail audit logs.                                       │
│ approve    List, accept and reject approvals.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

!!! note "Extras"
    The MCP proxy needs the `mcp` extra (`pip install "agent-castellan[mcp]"`) and the LangGraph wrapper needs `[langgraph]`. Neither is needed on this page.

## 2. Write your first policy

Save this as `first-policy.yaml`. It has two roles and three rules.

```yaml title="first-policy.yaml"
--8<-- "docs/site/examples/first-policy.yaml"
```

Read it top to bottom:

- `defaults.effect: deny` means a call that no rule mentions is refused. This is the safe default.
- `no-secrets` denies any tool whose `path` argument looks like a secret file. Because **deny always wins**, no other rule can undo it.
- `read-workspace` lets the `planner` and `coder` roles read inside `/workspace`.
- `write-needs-approval` makes every `coder` write wait for a human.

## 3. Check calls from the command line

`castellan check` asks the policy about one call without running anything. The exit code is the answer: `0` allow, `1` deny, `2` ask.

```bash
castellan check first-policy.yaml --role coder --tool fs.read --args '{"path":"/workspace/app.py"}'
```

```text
ALLOW rule=read-workspace source=policy reason=rule 'read-workspace' matched
```

```bash
castellan check first-policy.yaml --role coder --tool fs.read --args '{"path":"/workspace/.env"}'
```

```text
DENY rule=no-secrets source=policy reason=Secret files are off limits
```

```bash
castellan check first-policy.yaml --role coder --tool fs.write --args '{"path":"/workspace/app.py","content":"x"}'
```

```text
ASK rule=write-needs-approval source=policy reason=Writes need a human OK
```

A tool that no rule mentions falls to the default:

```bash
castellan check first-policy.yaml --role coder --tool shell.run --args '{"cmd":"ls"}'
```

```text
DENY rule=- source=default reason=no rule matched; default is deny
```

Castellan cleans up paths *before* matching, so `..` tricks do not work. This read tries to climb out of `/workspace`, and no rule allows the cleaned path:

```bash
castellan check first-policy.yaml --role coder --tool fs.read --args '{"path":"/workspace/../etc/passwd"}'
```

```text
DENY rule=- source=default reason=no rule matched; default is deny
```

## 4. Authorize calls from Python

In a real agent you call the **guard** instead of the CLI. The guard runs the whole pipeline: policy, delegation grants, approvals, budgets and the audit log. This script does everything in the rest of this page:

``` { .python title="getting_started.py" }
--8<-- "docs/site/examples/getting_started.py"
```

Run it from the folder that holds `first-policy.yaml`:

```bash
python getting_started.py
```

```text
principal: planner depth 0 run run-0d96...
allow read-workspace - rule 'read-workspace' matched
deny no-secrets - Secret files are off limits
coder depth: 1 | grant tools: ['fs.read']
deny grant - tool 'fs.write' is not covered by grant 0 (grant-9fba4e4c663090fb)
ask write-needs-approval approval_id set: True
approval status: approved
allow approval - approved request for rule 'write-needs-approval'
ask (a second retry asks again)
```

Here is what each part showed:

1. **Allow and deny.** `guard.authorize` returned a `Decision`. Its `effect`, `rule_id` and `reason` say what happened and why. `start_run("planner", on_behalf_of="alice")` created the root agent of a new *run*.
2. **Delegation.** `guard.delegate` created a child `coder` and a **grant** that lets it use only `fs.read`. When the coder tried `fs.write`, the *policy* said `ask`, but the *grant* said no, and the result was a `deny` from source `grant`. A grant can only turn an allow or ask into a deny, never the other way.
3. **Approval.** A second coder with a wider grant (`fs.*`) hit the `ask` rule. The decision carried an `approval_id`. After `guard.approve(...)`, retrying the *same call* succeeded with source `approval`.
4. **Single use.** An approval unlocks exactly one call. The next identical call asked again.

!!! warning "Keep the root key stable"
    `Guard.from_file(..., key=...)` signs grants with a key. The script uses a random one, which is fine inside one process. To pass grants between processes, give every process the same key (at least 32 bytes), either with `key=` or the hex-encoded `CASTELLAN_KEY` environment variable. Without either, Castellan generates a random key and emits a `RuntimeWarning`.

## 5. Look at the audit log

`authorize` wrote six entries to `castellan-audit.jsonl`, each carrying the hash of the one before it. Verify the chain:

```bash
castellan audit verify castellan-audit.jsonl
```

```text
OK: 6 entries verified
```

## Pitfalls

- **`check` is a dry run.** It never creates approvals or counts budgets. Use `Guard.authorize` in your agents.
- **Roles are strings.** A typo such as `coder ` in a rule silently matches nothing. Run `castellan lint` (see [testing and linting](guides/testing-and-linting.md)).
- **`ask` needs a retry.** Your tool wrapper must catch the `ask`, wait for the approval, and call again.

## Where to go next

- [Concepts](concepts.md): principals, grants, runs and the exact decision algorithm.
- [Writing policies](guides/writing-policies.md): grow this policy into a multi-agent one.
- [Multi-agent delegation](guides/delegation.md) and [Approvals](guides/approvals.md): the two features used in step 4, in depth.
