# CLI reference

*Who this page is for:* anyone running Castellan from a terminal, a script or CI. *After reading it* you will know every command, option and exit code, and what each command prints. The `--help` text below is pasted from the installed tool, so it matches exactly.

The command is `castellan`. Run `castellan --help` to list the commands. Every command that reads a policy exits with code **3** and prints `error: <message>` to standard error when the policy or an input cannot be read.

## Exit codes at a glance

| Command | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `check`, `explain` | allow | deny | ask (approval needed) | error |
| `test` | all cases passed | a case failed, or a file could not be run | | |
| `lint` | no error-severity finding | at least one error-severity finding | | policy could not be loaded |
| `audit verify` | chain intact | chain broken | | file could not be read |
| `audit tail` | ok | | | file could not be read or parsed |
| `approve list` | ok | | | state file could not be opened |
| `approve accept`, `approve reject` | request ended in the wanted state | it did not | | error, such as an unknown id |
| `mcp-proxy` | the server exited with 0 | | | |

!!! warning "Exit code 2 has two meanings"
    For `check` and `explain`, exit code 2 means *ask*. Typer also uses 2 for a command-line usage mistake, such as a missing `--tool`. A script that tests for 2 should first make sure it passed valid options.

## `castellan check`

Dry-runs one tool call against a policy and prints the decision. Nothing is recorded, no budget is used and no approval is created. It builds a throwaway agent from `--role`, `--depth`, `--parent-role` and `--on-behalf-of`. It evaluates the **policy only**: there are no grants on the command line, so a delegated agent's grant chain is not checked.

```text

 Usage: castellan check [OPTIONS] {policy}

 Dry-run one tool call against a policy and print the decision.

 Exit codes: 0 allow, 1 deny, 2 ask (approval needed), 3 error.

 Example: castellan check team.yaml --role coder --tool fs.write --args
 '{"path": "/w/a"}'

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    policy      <path>  Policy YAML file. [required]                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --role                <str>               Role of the calling agent.      │
│                                              [required]                      │
│ *  --tool                <str>               Tool name, for example          │
│                                              fs.write.                       │
│                                              [required]                      │
│    --args                <str>               Tool arguments as a JSON        │
│                                              object.                         │
│                                              [default: {}]                   │
│    --depth               <int range> [x>=0]  Delegation depth of the agent.  │
│                                              [default: 0]                    │
│    --parent-role         <str>               Role of the parent.             │
│    --on-behalf-of        <str>               End-user id.                    │
│    --help                <bool>              Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

The output is one line: `EFFECT rule=<id or -> source=<policy|default|invalid> reason=<text>`.

```bash
castellan check team.yaml --role coder --tool fs.read --args '{"path": "/workspace/.env"}'
```

```text
DENY rule=no-secrets source=policy reason=Secret files are off limits
```

```bash
castellan check team.yaml --role coder --tool payments.charge --args '{"amount": 50, "currency": "USD"}'
```

```text
ASK rule=small-payments-only source=policy reason=rule 'small-payments-only' matched
```

Errors:

```bash
castellan check team.yaml --role coder --tool fs.read --args 'nope'
```

```text
error: --args is not valid JSON: Expecting value: line 1 column 1 (char 0)
```

`--args '[1]'` gives `error: --args must be a JSON object`. A bad policy gives the message described in the [policy language reference](policy-language.md#errors-and-how-to-fix-them). All three exit with 3.

## `castellan explain`

Same options and exit codes as `check`. It prints the decision line and then a table with one row per rule, showing whether it matched and why not.

```text

 Usage: castellan explain [OPTIONS] {policy}

 Show every rule considered for a call and why it matched or not.

 Takes the same options and exit codes as `castellan check`.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    policy      <path>  Policy YAML file. [required]                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --role                <str>               Role of the calling agent.      │
│                                              [required]                      │
│ *  --tool                <str>               Tool name, for example          │
│                                              fs.write.                       │
│                                              [required]                      │
│    --args                <str>               Tool arguments as a JSON        │
│                                              object.                         │
│                                              [default: {}]                   │
│    --depth               <int range> [x>=0]  Delegation depth of the agent.  │
│                                              [default: 0]                    │
│    --parent-role         <str>               Role of the parent.             │
│    --on-behalf-of        <str>               End-user id.                    │
│    --help                <bool>              Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

```bash
castellan explain team.yaml --role coder --tool fs.write --args '{"path": "/workspace/app.py", "content": "x"}' --depth 1
```

```text
ASK rule=write-needs-review source=policy reason=A reviewer must approve every write
                             Rule trace                              
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Rule                ┃ Matched ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ no-secrets          │ no      │ when: condition is false          │
│ read-workspace      │ no      │ tools: no match for 'fs.write'    │
│ write-needs-review  │ yes     │ matched                           │
│ shallow-web         │ no      │ agents: no match for role 'coder' │
│ small-payments-only │ no      │ tools: no match for 'fs.write'    │
└─────────────────────┴─────────┴───────────────────────────────────┘
```

The `Detail` column is one of `agents: no match for role '<role>'`, `tools: no match for '<tool>'`, `when: condition is false` or `matched`. The check order is agents, then tools, then `when`, and the first failing part is reported.

## `castellan test`

Runs policy test files and reports pass or fail, like a unit-test runner. The file format is described in [testing and linting](../guides/testing-and-linting.md#policy-test-files).

```text

 Usage: castellan test [OPTIONS] {files}...

 Run policy test files (YAML with a policy path and cases) and report
 pass/fail.

 Exit 1 if any case fails or a file cannot be run. Use --junit for CI reports.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    files...      <list[Path]>  Policy test YAML files. [required]          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --junit        <path>  Write a JUnit XML report.                             │
│ --help         <bool>  Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Output: one line per file with a dot for each passing case, `F` for a failure and `E` if the file could not be run, then the failures, then a summary.

```bash
castellan test failing.test.yaml
```

```text
failing.test.yaml .FF

=== FAILURES ===
FAILED failing.test.yaml::coder write is allowed outright
    expected allow, got ask (rule: write-needs-review, reason: A reviewer must approve every write)
FAILED failing.test.yaml::wrong rule named
    expected rule read-workspace, got no-secrets

=== 1 passed, 2 failed in 0.01s ===
```

With `--junit out.xml` the same results are written as a JUnit XML report that CI systems can display. A file that cannot be run (missing policy, invalid test file) counts as an error and makes the exit code 1:

```text
ERROR broken.test.yaml: nowhere.yaml cannot read policy file: [Errno 2] No such file or directory: 'nowhere.yaml'
```

## `castellan lint`

Static checks on a policy: shadowed, duplicate, over-broad and unreachable rules. Every check is explained in [testing and linting](../guides/testing-and-linting.md#lint-checks).

```text

 Usage: castellan lint [OPTIONS] {policy}

 Find shadowed, duplicate, over-broad and unreachable rules (checks L001-L007).

 Exit 1 if any error-severity finding exists. --format github emits workflow
 annotations.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    policy      <path>  Policy YAML file. [required]                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format        <text|json|github>  Output format. [default: text]           │
│ --help          <bool>              Show this message and exit.              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

`--format` chooses the output:

- `text` (default): `<file>:<line>: <severity> <id> <message> [<rule id>]`, or `no issues found`.
- `json`: a list of objects with `check_id`, `severity`, `message`, `rule_id` and `line`.
- `github`: GitHub Actions workflow annotations (`::error file=...,line=...,title=L002::...`).

```bash
castellan lint lint-demo.yaml
```

```text
lint-demo.yaml:17: warning L001 allow rule 'allow-shell-ls' is shadowed by unconditional deny rule 'no-shell' and can never take effect [allow-shell-ls]
lint-demo.yaml:26: error L002 duplicate rule id 'read-anything' [read-anything]
lint-demo.yaml:22: warning L003 rule 'read-anything' allows every tool with no conditions [read-anything]
lint-demo.yaml:36: error L004 rule 'web-for-intern' references role 'intern' in agents which is not defined in 'agents' [web-for-intern]
lint-demo.yaml: error L004 role 'planner' can_delegate_to undefined role 'ghost'
lint-demo.yaml:30: warning L005 ask rule 'write-needs-audit' needs approver role 'auditor' which can never exist in a run [write-needs-audit]
lint-demo.yaml: warning L006 role 'auditor' is not reachable from any can_delegate_to chain
lint-demo.yaml: warning L007 defaults.effect is 'allow': unmatched calls are permitted
```

The exit code is 1 here because two findings are errors. Warnings alone exit 0.

## `castellan audit`

Commands for the hash-chained [audit log](../guides/audit.md).

```text

 Usage: castellan audit [OPTIONS] COMMAND [ARGS]...

 Verify and tail audit logs.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ verify  Verify the hash chain. Exit 0 if intact, 1 if tampered, 3 on failure │
│         to read.                                                             │
│ tail    Show the most recent audit entries, optionally for one run.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `castellan audit verify`

```text

 Usage: castellan audit verify [OPTIONS] {file}

 Verify the hash chain. Exit 0 if intact, 1 if tampered, 3 on failure to read.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    file      <path>  Audit log (JSONL) file. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Checks every entry's hash and that the sequence numbers run from 0 without gaps.

```bash
castellan audit verify castellan-audit.jsonl
```

```text
OK: 4 entries verified
```

If an entry was edited, or one was removed from the middle:

```text
FAILED at seq 1: hash_mismatch
```

```text
FAILED at seq 2: gap
```

Both exit with 1. The reason is `hash_mismatch`, `gap` or `reordered`. A bare hash chain cannot detect entries removed from the *end* of the log; see the [security model](../about/security.md).

### `castellan audit tail`

```text

 Usage: castellan audit tail [OPTIONS] {file}

 Show the most recent audit entries, optionally for one run.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    file      <path>  Audit log (JSONL) file. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --run            <str>               Only entries of this run id.            │
│ --lines  -n      <int range> [x>=1]  Entries to show. [default: 20]          │
│ --help           <bool>              Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Prints the most recent entries, oldest first, one per line.

```bash
castellan audit tail castellan-audit.jsonl -n 2
```

```text
2 2026-11-26T21:28:26.362694+00:00 run=run-be82d654aae99e55 agent=agent-2b3be3b723e8 role=coder tool=fs.write effect=ask rule=write-needs-approval
3 2026-11-26T21:28:28.882438+00:00 run=run-be82d654aae99e55 agent=agent-2b3be3b723e8 role=coder tool=fs.write effect=allow rule=write-needs-approval
```

The fields are: sequence number, UTC time, run id, agent id, role, tool, effect and rule id (`-` when a default decided).

## `castellan approve`

Lists and answers approval requests kept in a SQLite state file. Create that file by giving `Guard.from_file` a `state_path`; see [approvals](../guides/approvals.md).

```text

 Usage: castellan approve [OPTIONS] COMMAND [ARGS]...

 List, accept and reject approvals.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list    List approvals that are waiting for a decision.                      │
│ accept  Approve a pending request. Exit 1 if it could not be approved.       │
│ reject  Reject a pending request. Exit 1 if it could not be rejected.        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `castellan approve list`

```text

 Usage: castellan approve list [OPTIONS]

 List approvals that are waiting for a decision.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --state        <path>  SQLite state file. [required]                      │
│    --help         <bool>  Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

```bash
castellan approve list --state state.db
```

```text
                                                       Pending approvals
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Approval              ┃ Run                  ┃ Agent                      ┃ Tool     ┃ Args                                     ┃ Approver ┃ Rule                 ┃ Expires                          ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ appr-b1df961e8987255d │ run-e0d77e9c31884910 │ agent-fe5a5b58f9d2 (coder) │ fs.write │ {"content": "x", "path":                 │ human    │ write-needs-approval │ 2026-11-26T21:38:12.362791+00:00 │
│                       │                      │                            │          │ "/workspace/app.py"}                     │          │                      │                                  │
└───────────────────────┴──────────────────────┴────────────────────────────┴──────────┴──────────────────────────────────────────┴──────────┴──────────────────────┴──────────────────────────────────┘
```

With nothing waiting it prints `no pending approvals`. The table is wide; in a narrow terminal long ids may be cut, so widen the window before copying an id.

### `castellan approve accept`

```text

 Usage: castellan approve accept [OPTIONS] {approval_id}

 Approve a pending request. Exit 1 if it could not be approved.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    approval_id      <str>  Approval id. [required]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --state           <path>  SQLite state file. [required]                   │
│    --approver        <str>   Id of the approving party. [default: human]     │
│    --help            <bool>  Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

```bash
castellan approve accept appr-e024fdb788310ef0 --state state.db
```

```text
appr-e024fdb788310ef0: approved
```

The agent then retries the *same call*, and `Guard.authorize` returns `allow` with source `approval`. Answering a request that is no longer pending is not an error: the command prints its current status. An unknown id exits with 3:

```text
error: cannot resolve approval 'nope': unknown approval id 'nope'
```

### `castellan approve reject`

```text

 Usage: castellan approve reject [OPTIONS] {approval_id}

 Reject a pending request. Exit 1 if it could not be rejected.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    approval_id      <str>  Approval id. [required]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --state           <path>  SQLite state file. [required]                   │
│    --approver        <str>   Id of the approving party. [default: human]     │
│    --help            <bool>  Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Works like `accept` but denies the request; it prints `<id>: denied`.

!!! note
    `--approver` defaults to `human`, which satisfies rules with `approver: human`. The command has no option for naming the approver's role, so `role:<role>` approvers cannot be satisfied from the command line (nor through `Guard.approve`; see the [policy language reference](policy-language.md#approver-values)).

## `castellan mcp-proxy`

Runs an MCP server behind a stdio proxy that enforces the policy on every `tools/call`. It needs the `mcp` extra. Configuration examples for MCP clients are in [integrations](../guides/integrations.md).

```text

 Usage: castellan mcp-proxy [OPTIONS] {server_command}...

 Run an MCP server behind a policy-enforcing stdio proxy: castellan mcp-proxy
 --policy team.yaml --role coder -- <server command...>

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    server_command...      <list[str]>  Server command (after `--`).        │
│                                          [required]                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --policy              <path>  Policy YAML file. [required]                │
│ *  --role                <str>   Role the proxied client acts as. [required] │
│    --server-name         <str>   Name used in tool names (default: command   │
│                                  name).                                      │
│    --hide-denied         <bool>  Hide tools the role can never use from      │
│                                  tools/list.                                 │
│    --state               <path>  SQLite state path.                          │
│    --on-behalf-of        <str>   End-user id.                                │
│    --help                <bool>  Show this message and exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

The proxy exits with the server's exit code. Everything after `--` is the server command.

## Pitfalls

- **Shell quoting.** `--args` must be a JSON object in one shell argument. Use single quotes around it on Linux and macOS.
- **Relative policy paths in test files.** A `policy:` path in a test file is relative to the *test file*, not to your working directory.
- **Reading exit code 2 as ask.** See the warning above.

## Where to go next

- [Testing and linting](../guides/testing-and-linting.md): using `test` and `lint` in CI.
- [Policy language reference](policy-language.md): what the policy files contain.
- [Python API](python-api.md): the same engine from code.
