# Testing and linting policies

*Who this page is for:* anyone who maintains a policy and wants to change it without fear. *After reading it* you will be able to write test files for a policy, understand every lint finding and how to fix it, and run both in CI with GitHub Actions.

A policy is code that guards your agents, so treat it like code: **test** what it should decide, and **lint** it for mistakes that tests rarely catch (rules that can never fire, roles that do not exist, allow rules that cover everything). Both run offline, in milliseconds, with no agents involved.

| Tool | Question it answers |
|---|---|
| `castellan check` | What does the policy decide for this one call? |
| `castellan explain` | *Why*, rule by rule? |
| `castellan test` | Does the policy still decide what I expect, for all my cases? |
| `castellan lint` | Is the policy itself well formed and sensible? |

## Explain a decision

When a decision surprises you, run `explain` with the same options as `check`. The trace shows every rule in file order and why it did or did not match.

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

The same trace is available in Python as `decision.trace`.

## Policy test files

A test file names a policy and lists cases. Each case says who calls what and what you expect.

```yaml title="team.test.yaml"
--8<-- "docs/site/examples/team.test.yaml"
```

| Key | Required | Meaning |
|---|---|---|
| `policy` | yes | Path to the policy, **relative to the test file**. |
| `cases` | yes | List of cases. |
| `cases[].name` | yes | Shown in failure messages. |
| `cases[].agent` | yes | The caller. `role` is required; `depth` (default 0), `agent_id`, `run_id`, `parent_role` and `on_behalf_of` are optional. |
| `cases[].call` | yes | The call. `tool` is required; `args` and `resource` are optional. |
| `cases[].expect` | yes | `allow`, `deny` or `ask`. |
| `cases[].expect_rule` | no | The rule id that must have decided. Leave it out to check only the effect. A decision made by the default has no rule id. |

Unknown keys are errors, so a typo cannot hide a case. Cases test the **policy only**: grants, budgets and approvals are not part of them.

Run it:

```bash
castellan test team.test.yaml
```

```text
team.test.yaml .......

=== 7 passed in 0.01s ===
```

When a case fails, the message says what was expected and what happened. This file expects a coder write to be allowed, and names the wrong rule for a secret:

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

The exit code is 1. Pass several files at once, and add `--junit report.xml` to produce a JUnit report for your CI system.

### What to test

- **Every deny you rely on.** "Coder cannot read `.env`" is more valuable than "coder can read the workspace".
- **Boundaries.** The largest allowed amount, the deepest allowed depth, a path with `..` in it.
- **Each role** against a tool it must *not* have.
- **`expect_rule`** for the rules that carry security meaning, so a later edit cannot make a different rule decide.

## Lint checks

`castellan lint` finds problems in the policy itself. Each finding has an id, a severity, a message, the rule id and the line of the rule.

```bash
castellan lint lint-demo.yaml
```

```text
--8<-- "docs/site/examples/lint-demo.out.txt"
```

Findings with severity `error` make the command exit 1; warnings alone exit 0. Here is the file that produced that output, with the check each line triggers:

```yaml title="lint-demo.yaml"
--8<-- "docs/site/examples/lint-demo.yaml"
```

### L001: shadowed allow {#l001-shadowed-allow}

*Severity: warning.* An `allow` rule is completely covered by an unconditional `deny` rule (one without `when`) that matches the same tools and roles. Because deny always wins, the allow can never take effect. Rule order does not matter here.

*Why it matters:* the author clearly meant the call to work, and it will not. A test would have caught it:

```bash
castellan test shadow.test.yaml
```

```text
shadow.test.yaml F

=== FAILURES ===
FAILED shadow.test.yaml::coder may run ls
    expected allow, got deny (rule: no-shell, reason: rule 'no-shell' matched)

=== 0 passed, 1 failed in 0.01s ===
```

*Fix:* narrow the deny (add a `when`, or list only the tools it should block), or delete the dead allow.

The check is conservative: it only reports shadowing it can prove, so a clean lint does not prove every rule is reachable.

### L002: duplicate rule id {#l002-duplicate-rule-id}

*Severity: error.* Two rules share an `id`. Ids appear in decisions, traces and audit entries, and approvals are tied to them, so they must be unique. The finding points at the second use.

*Fix:* rename one rule.

### L003: wildcard allow {#l003-wildcard-allow}

*Severity: warning.* An `allow` rule matches every tool (`tools: ["*"]`, or omitted) and has no `when`. For the roles it names, nothing is restricted by tool any more.

```yaml
rules:
  - id: everything
    effect: allow
```

```text
l3.yaml:3: warning L003 rule 'everything' allows every tool with no conditions [everything]
```

*Fix:* list the tools, or add a `when` that limits the arguments. If you really want it (for example in a throwaway test policy), accept the warning.

### L004: undefined role {#l004-undefined-role}

*Severity: error.* A role is used but not declared under `agents`. This happens in three places: a rule's `agents` list, a `role:<role>` approver, and a `can_delegate_to` list. A typo in a role name silently makes a rule match nobody, which is why this is an error.

*Fix:* declare the role (`coder: {}`) or correct the spelling. Wildcard role patterns and `*` are not checked.

### L005: approver role can never exist {#l005-approver-role-can-never-exist}

*Severity: warning.* An `ask` rule names `approver: role:<role>`, the role is declared, but no delegation chain can ever create an agent of that role. The request would wait for an approver that never exists. This check only runs when at least one role has a `can_delegate_to`.

For example, removing `reviewer` from the planner's `can_delegate_to` in the team policy:

```text
team-broken.yaml:32: warning L005 ask rule 'write-needs-review' needs approver role 'reviewer' which can never exist in a run [write-needs-review]
team-broken.yaml: warning L006 role 'reviewer' is not reachable from any can_delegate_to chain
```

*Fix:* add the role to some role's `can_delegate_to`, or use `approver: human`.

### L006: unreachable role {#l006-unreachable-role}

*Severity: warning.* A declared role is neither a root (a role that delegates but nobody delegates to it) nor reachable from one through `can_delegate_to`. No agent of that role can exist in a run. The finding has no line number, because it concerns a role, not a rule. It only runs when at least one role has a `can_delegate_to`.

*Fix:* add the role to a `can_delegate_to` list, or remove it. If the role is meant to be the root of its own runs, give it a `can_delegate_to` of its own.

### L007: default allow {#l007-default-allow}

*Severity: warning.* `defaults.effect` is `allow`, so any call that no rule mentions is permitted. New tools are therefore open by default.

*Fix:* set `defaults.effect: deny` and add allow rules for what you need. Keep `allow` only for a policy whose job is to forbid a short list of things.

## Run both in CI

Put the policy and its tests in the repository and run the commands on every pull request. `--format github` turns findings into inline annotations on the changed lines.

```yaml title=".github/workflows/policy.yml"
name: policy

on:
  pull_request:
    paths: ["policies/**"]

jobs:
  policy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install agent-castellan
      - name: Lint policies
        run: castellan lint policies/team.yaml --format github
      - name: Test policies
        run: castellan test policies/tests/*.test.yaml --junit policy-report.xml
      - name: Keep the report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: policy-report
          path: policy-report.xml
```

`lint` fails the job on errors (L002, L004) and annotates warnings without failing. To fail on warnings too, run `castellan lint --format json` and check that the list is empty, for example with `jq -e 'length == 0'`.

## Pitfalls

- **Testing only allows.** A policy that allows everything passes every "allow" test. Test the denials.
- **Relative `policy:` paths.** They are relative to the test file, not the directory you run from.
- **Assuming lint covers behavior.** Lint finds structural mistakes. It cannot know what you intended; tests do.
- **Expecting grants or budgets in tests.** Test files exercise the policy only. Test delegation and budgets in Python with `Guard`.

## Where to go next

- [CLI reference](../reference/cli.md): every option and exit code.
- [Policy language reference](../reference/policy-language.md): what each key and operator means.
- [Writing policies](writing-policies.md): grow a policy, testing as you go.
