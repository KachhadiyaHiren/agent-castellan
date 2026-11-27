# Glossary

The terms below are used with exactly these meanings in the code, the CLI and these docs.
Entries are in alphabetical order.

## Approval
A request to let one specific call through, created when a rule's effect is `ask`. It is bound
to the exact tool and arguments, to one agent and run, is single-use, and expires. Statuses:
`pending`, `approved`, `denied`, `expired`, `consumed`. See [Approvals](../guides/approvals.md).

## Approver
The party allowed to resolve an approval, set by the rule's `approver` field: `human`,
`role:<role>` or `agent:<id>`. An agent can never approve its own request.

## Attenuation
Making a grant narrower than its parent: fewer tools, a shorter life, fewer calls, more
conditions. Grants can only be attenuated, never widened. See
[Delegation](../guides/delegation.md#how-grants-shrink).

## Audit log
The append-only JSONL file where every `authorize` decision is recorded, each entry carrying
the hash of the previous one. See [Audit log](../guides/audit.md).

## Budget
A ceiling on tool calls or cost units for a run or a role. See [Budgets](../guides/budgets.md).

## Call hash
The SHA-256 of the canonical JSON of a call's tool name and arguments. Approvals are bound to it.

## Chain (grant chain)
The grants from the first delegation down to one agent, each signed with the previous grant's
signature. Written as tokens joined by dots when sent between processes.

## Condition
The data-only expression in a rule's `when` block. Built from operators such as `eq`, `glob`
and `lte`, and combinators `all`, `any` and `not`. Nothing in it is ever executed as code.
See the [policy language reference](../reference/policy-language.md).

## Cost units
A number the caller attaches to a call (`ToolCall.cost_units`) to describe what it costs, so a
run can have a spending ceiling. Castellan does not measure cost itself.

## Decision
The result of authorizing a call: `effect`, `reason`, `rule_id` (or none for the default),
`source`, a `trace` of the rules considered, and an `approval_id` when the effect is `ask`.

## Default effect
What happens when no rule matches: `defaults.effect`, which is `deny` unless you change it.

## Delegation
An agent creating a sub-agent and handing it a grant. See [Delegation](../guides/delegation.md).

## Deny overrides
The decision rule: if any matching rule denies, the call is denied, regardless of priority.
See [Architecture](architecture.md#deny-overrides-everything).

## Effect
The outcome of a rule or decision: `allow`, `deny` or `ask`.

## Grant
A signed delegation from a parent agent to a child: allowed tool globs, optional extra
conditions, an expiry and an optional call limit. A grant can never give more than the policy
allows. See [Delegation](../guides/delegation.md).

## Guard
The object that runs the authorization pipeline: budget check, policy, grants, approval,
audit. `Guard.authorize` is the entry point.

## Normalization
Turning a call into one canonical form before matching: lower-cased tool name, resolved paths,
cleaned URLs. It stops tricks such as `/workspace/../etc/passwd`.

## Policy
A loaded, validated YAML file holding the rules, agent roles, budgets, approval settings and
audit path.

## Principal
An agent identity in one run: `agent_id`, `role`, `run_id`, `parent_id`, `parent_role`,
`depth` and `on_behalf_of`. See [Concepts](../concepts.md).

## Role
A named kind of agent (`planner`, `coder`) that rules and budgets refer to. Agent ids are
assigned at runtime; roles are written in the policy.

## Root key
The secret that signs the first grant of every chain. See
[Key management](security.md#key-management).

## Rule
One entry in the policy: an `id`, which `agents` and `tools` it covers, an optional `when`
condition, an `effect`, and optionally a `reason`, an `approver` and a `priority`.

## Run
One top-level task. Every principal in one delegation tree shares a `run_id` and a run budget.
Started with `Guard.start_run`.

## Source
Which stage produced a decision: `policy`, `grant`, `budget`, `approval`, `default` or `invalid`.

## Tool call
The thing being authorized: a namespaced `tool` name such as `fs.write` or
`mcp:files/read_file`, its `args`, optional `resource` attributes and `cost_units`.

## Trace
The list in a decision showing every rule considered and whether it matched, with a short
reason. `castellan explain` prints it as a table.
