# Writing policies

*Who this page is for:* someone who has run the [getting started](../getting-started.md) page and now wants to write a real policy. *After reading it* you will be able to build a multi-agent policy rule by rule, and you will know why each rule is there. Every output below came from running the policy shown.

We build four policies, each a small step from the last:

1. one rule,
2. a safe default and a secrets rule,
3. conditions and approvals,
4. a team of agents with delegation and budgets.

## Step 1: one rule

```yaml title="step1.yaml"
--8<-- "docs/site/examples/step1.yaml"
```

A policy needs `version: 1`. Each rule needs an `id` and an `effect`. This rule lets any role call `fs.read`.

```bash
castellan check step1.yaml --role anyone --tool fs.write --args '{"path":"/x"}'
```

```text
DENY rule=- source=default reason=no rule matched; default is deny
```

A call that no rule matches is denied, because `defaults.effect` is `deny` unless you say otherwise. That is the right default: you list what is allowed, and everything else stays closed.

But look at what the rule allows:

```bash
castellan check step1.yaml --role anyone --tool fs.read --args '{"path":"/etc/passwd"}'
```

```text
ALLOW rule=read-workspace source=policy reason=rule 'read-workspace' matched
```

The rule is named `read-workspace` but it allows reading *any* file. A rule is only as narrow as its conditions.

## Step 2: narrow the rule, add a deny

```yaml title="step2.yaml"
--8<-- "docs/site/examples/step2.yaml"
```

Two things changed:

- `read-workspace` now has a `when` condition. `args.path` is the `path` argument of the call, and `glob: "/workspace/**"` means "anything under `/workspace`". The condition is data, not code: nothing in a policy is ever evaluated as Python.
- `no-secrets` applies to `tools: ["*"]`, every tool. `any:` means "at least one of these". It denies `.env` files and `.pem` keys wherever they are.

```bash
castellan check step2.yaml --role anyone --tool fs.read --args '{"path":"/workspace/notes.txt"}'   # ALLOW
castellan check step2.yaml --role anyone --tool fs.read --args '{"path":"/etc/passwd"}'            # DENY (default)
castellan check step2.yaml --role anyone --tool fs.read --args '{"path":"/workspace/.env"}'
```

```text
ALLOW rule=read-workspace source=policy reason=rule 'read-workspace' matched
DENY rule=- source=default reason=no rule matched; default is deny
DENY rule=no-secrets source=policy reason=Secret files are off limits
```

The last call matches **both** rules: `/workspace/.env` is inside the workspace, and it is a secret. `explain` shows how Castellan settled it:

```bash
castellan explain step2.yaml --role anyone --tool fs.read --args '{"path":"/workspace/.env"}'
```

```text
DENY rule=no-secrets source=policy reason=Secret files are off limits
              Rule trace              
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓
┃ Rule           ┃ Matched ┃ Detail  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩
│ read-workspace │ yes     │ matched │
│ no-secrets     │ yes     │ matched │
└────────────────┴─────────┴─────────┘
```

**Deny always beats allow**, whatever the order of the rules or their `priority`. That is why a `deny` rule is a safe place to put "never, whoever asks".

## Step 3: conditions and approvals

```yaml title="step3.yaml"
--8<-- "docs/site/examples/step3.yaml"
```

The new rule, `small-payments`, shows three more ideas:

- `tools: ["payments.*"]` matches `payments.send`, `payments.refund` and so on. In tool names `*` stops at a dot; `**` does not.
- `all:` requires every condition. Here the amount must be at most 100 *and* the currency must be USD or EUR.
- `effect: ask` does not allow the call; it asks `approver: human` first. `reason` is the message the caller sees.

```bash
castellan check step3.yaml --role anyone --tool payments.send --args '{"amount":50,"currency":"EUR"}'   # exit 2
castellan check step3.yaml --role anyone --tool payments.send --args '{"amount":500,"currency":"EUR"}'  # exit 1
castellan check step3.yaml --role anyone --tool payments.send --args '{"currency":"EUR"}'               # exit 1
```

```text
ASK rule=small-payments source=policy reason=Payments always need a human
DENY rule=- source=default reason=no rule matched; default is deny
DENY rule=- source=default reason=no rule matched; default is deny
```

Two surprises, both deliberate:

- A 500 payment is **denied**, not asked. The rule only matches small payments; larger ones match nothing and fall to the default. Writing "ask for small, deny for large" is a statement about what *does not* match.
- A payment with no `amount` is denied. A condition on a path that is missing is **false** (the one exception is `exists: false`), so a call cannot skip a check by leaving out the argument.

## Step 4: a team

Real systems have several agents. Castellan models each one by its **role** and lets one agent delegate to another. This is the full team policy:

```yaml title="team.yaml"
--8<-- "docs/site/examples/team.yaml"
```

Why each part is there:

`agents`
:   Declares the roles and who may delegate to whom. `planner` can create `researcher`, `coder` and `reviewer` agents, and `max_delegation_depth: 2` stops delegation chains from growing deeper than two levels. The others delegate to nobody. Every role named in a rule should be declared here, and the linter checks that.

`no-secrets`
:   The same "never" rule as in step 2, now guarding the whole team.

`read-workspace`
:   `agents: [researcher, coder, reviewer]` limits the rule to those roles. The planner has no tool rule at all: it plans and delegates, but cannot touch files itself.

`write-needs-review`
:   Coder writes pause for an approver. `approver: role:reviewer` says any `reviewer` agent in the same run may approve. An agent can never approve its own request.

`shallow-web`
:   Researchers may search the web only while `agent.depth` is at most 2. A researcher spawned too deep gets nothing. Conditions can read the caller (`agent.*`), the tool (`tool.*`), the arguments (`args.*`), the run (`run.*`) and the clock (`time.*`).

`budgets`
:   `run` caps all tool calls in a run, whatever the agent; `per_role` adds limits per role. See [budgets](budgets.md).

Now run it. This script starts a run as the planner, delegates two sub-agents with narrow grants, and makes calls:

``` { .python title="team_demo.py" }
--8<-- "docs/site/examples/team_demo.py"
```

```text
researcher web.search   -> allow rule=shallow-web source=policy
researcher fs.read      -> deny  rule=None source=grant
coder      fs.read      -> deny  rule=no-secrets source=policy
coder      fs.write     -> ask   rule=write-needs-review source=policy
coder      web.search   -> deny  rule=None source=default
researcher cannot delegate: role 'researcher' may not delegate to 'coder' at depth 1
```

Read the `source` column: it tells you which stage decided.

- `researcher fs.read` is **allowed by the policy**, but the researcher's grant only lists `web.*`, so the *grant* denied it. The planner decided how much to hand down, and the researcher cannot take more.
- `coder fs.read` of `.env` is stopped by `no-secrets` even though the coder holds `fs.*`.
- `coder web.search` is denied by default: no rule lets a coder search the web.
- The last line is the `agents` section at work. The researcher has no `can_delegate_to`, so it cannot create any agent.

## Test the policy

A policy this size deserves tests. Save [`team.test.yaml`](../examples/team.test.yaml) next to `team.yaml` and run it:

```bash
castellan test team.test.yaml
```

```text
team.test.yaml .......

=== 7 passed in 0.01s ===
```

The [testing and linting guide](testing-and-linting.md) explains the file format and the linter.

## Habits that keep policies safe

- **Default to deny** and add the narrowest allow you can.
- **Put "never" in a deny rule** with a `reason`. It cannot be overridden.
- **Give every `ask` rule an approver** and make sure that role can exist in a run.
- **Match roles, not agent ids.** Ids change every run.
- **Test the deny cases**, not only the allow cases.
- **Lint in CI.** See [testing and linting](testing-and-linting.md).

## Pitfalls

- **Broad globs.** `tools: ["*"]` with `effect: allow` and no `when` allows everything; the linter flags it as `L003`.
- **Case.** Tool names are lower-cased before matching, so write patterns in lower case.
- **Path tricks.** Castellan resolves `..` in path-like arguments before matching, but only for argument names it recognizes as paths (`path`, `file`, `dir`, anything ending in `_path`, and a few others). A path hidden in an argument with an unusual name is treated as plain text. The [policy language reference](../reference/policy-language.md#call-normalization) lists the names.
- **Role approvers.** `role:<role>` approvers are accepted by the language and the linter, but `Guard.approve` cannot yet satisfy them (it does not know the approver's role). Use `human` or `agent:<id>` approvers for now.

## Where to go next

- [Policy language reference](../reference/policy-language.md): every key and operator.
- [Multi-agent delegation](delegation.md): how grants work in depth.
- [Approvals](approvals.md): the retry pattern after an `ask`.
