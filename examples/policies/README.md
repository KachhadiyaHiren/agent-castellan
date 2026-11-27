# Policy cookbook

Ten complete, tested policies you can copy, rename and adapt. **Audience:** you have read the
[README](../../README.md) and want to see how real rules look for real jobs. After this
page you can pick the closest policy to your use case and have it running in minutes.

Every policy has the same three parts:

- a **header comment** that explains the scenario and the pattern it shows,
- **a comment on every rule** that says *why* it exists, not just what it does,
- a **test file** in [`tests/`](tests) that proves it behaves as described.

All ten share one safety stance: `defaults.effect: deny`. If no rule matches, the call is
refused. That means a tool you forgot about is blocked, not silently allowed.

## Use a policy

Check one call (exit code 0 allow, 1 deny, 2 ask, 3 error):

```bash
uv run castellan check examples/policies/github-agent.yaml \
  --role github_agent --tool github.push_branch \
  --args '{"repo": "acme/app", "branch": "main"}'
```

```text
DENY rule=no-push-to-default-branch source=policy reason=Push to a feature branch and open a pull request instead
```

Run every test file, and lint every policy (checks L001-L007):

```bash
uv run castellan test examples/policies/tests/*.test.yaml
for p in examples/policies/*.yaml; do uv run castellan lint "$p"; done
```

```text
examples/policies/tests/coding-sandbox.test.yaml ..........
examples/policies/tests/customer-support.test.yaml ..........
examples/policies/tests/database-readonly.test.yaml ..........
examples/policies/tests/github-agent.test.yaml ........
examples/policies/tests/office-hours.test.yaml ....
examples/policies/tests/payments-approval.test.yaml .......
examples/policies/tests/research-agent.test.yaml ........
examples/policies/tests/research-team.test.yaml .............
examples/policies/tests/staging-vs-prod.test.yaml ........
examples/policies/tests/two-person-rule.test.yaml .....

=== 83 passed in 0.10s ===
```

## Index

| Policy | Test file | Pattern it teaches |
|---|---|---|
| [research-agent.yaml](research-agent.yaml) | [tests](tests/research-agent.test.yaml) | allow-list plus a deny for the allow-list's biggest hole |
| [coding-sandbox.yaml](coding-sandbox.yaml) | [tests](tests/coding-sandbox.test.yaml) | path globs, secrets deny, command allow-list |
| [payments-approval.yaml](payments-approval.yaml) | [tests](tests/payments-approval.test.yaml) | `ask`, numeric limits, hard ceiling |
| [github-agent.yaml](github-agent.yaml) | [tests](tests/github-agent.test.yaml) | never-list, argument-conditioned deny |
| [database-readonly.yaml](database-readonly.yaml) | [tests](tests/database-readonly.test.yaml) | `regex` on a query string |
| [customer-support.yaml](customer-support.yaml) | [tests](tests/customer-support.test.yaml) | refund ladder, `exists`, data exclusion |
| [office-hours.yaml](office-hours.yaml) | [tests](tests/office-hours.test.yaml) | `time.hour_utc`, `time.weekday` |
| [two-person-rule.yaml](two-person-rule.yaml) | [tests](tests/two-person-rule.test.yaml) | `approver: role:lead` |
| [staging-vs-prod.yaml](staging-vs-prod.yaml) | [tests](tests/staging-vs-prod.test.yaml) | one tool, different effect per `args.env` |
| [research-team.yaml](research-team.yaml) | [tests](tests/research-team.test.yaml) | delegation, depth, `parent_role`, shared budgets |

## The policies

### Read-only research agent

An agent that searches the web and reads pages, and can change nothing. It may only fetch
`https://` URLs, and a deny rule blocks localhost, private ranges, cloud-metadata addresses
and `file:` URLs so that a prompt-injected page cannot point the agent at your network.
A run budget stops runaway loops. Start here if you are new: it is short and shows the
deny-beats-allow rule in action.

### Coding agent in a sandbox directory

An agent that edits a project under `/workspace`. Reads and writes are allowed inside that
directory only; secrets (`.env`, `*.pem`, keys) are denied everywhere; deleting is not
granted; and `shell.run` accepts only an exact list of commands, so `pytest; curl ... | sh`
is refused. Castellan normalizes paths before matching, which is why
`/workspace/../etc/passwd` does not escape.

### Payments with approval

A finance assistant that can list invoices and send payments. Payments up to 1000 in USD or
EUR are `ask` (a human approves each exact call), anything above 1000 is denied outright, and
other currencies are denied. The hard ceiling is a `deny`, so even an approver cannot raise it.

### GitHub agent

An agent that triages issues and opens pull requests. It can read, comment, create issues and
branches, push feature branches and open PRs. It can never delete or transfer a repository,
force-push, or push to `main`, and merging needs a human.

### Database agent (SELECT only)

An analyst agent that queries a reporting database. A `regex` rule denies write and DDL
keywords and semicolons, and another allows only statements that start with `SELECT` or
`WITH`. A regex is a coarse filter, not a SQL parser; the policy's header explains why you
should still give the agent a read-only database account.

### Customer-support agent

An agent that answers tickets. It cannot see card data, can email only the ticket owner (your
tool wrapper computes the `to_matches_ticket` flag, never the model), and refunds follow a
ladder: up to 25 automatic, up to 200 needs a human, above 200 denied.

### Office hours only

An operations agent that can restart or scale services only on weekdays from 09:00 to 17:00
UTC, and read at any time. Time rules cannot be tested with `castellan test`, which uses the
real clock, so the test file covers the time-independent rules and
[`office_hours_clock.py`](office_hours_clock.py) tests the window with a pinned clock:

```bash
uv run python examples/policies/office_hours_clock.py
```

```text
Wednesday 10:00 UTC: allow
Wednesday 17:00 UTC: deny
Saturday 10:00 UTC: deny
```

### Two-person rule

Production releases and secret rotation by an `operator` need approval from a `lead`
(`approver: role:lead`). The requester can never approve its own request, and a lead cannot
make the request either. Approvals are bound to the exact call, are single use and expire after
five minutes.

> **Known issue in the current development version:** `Guard.approve` does not yet pass the
> approver's role to the approval store, so `role:` approvers stay pending. `human:` and `agent:`
> approvers work. The policy and its tests are correct; remove this note when the fix lands.

### Staging vs production

A deploy agent with the same tools in two environments. In `staging` everything is automatic;
in `prod` deploys and rollbacks need a human and destroy is denied. An unknown or missing
`env` matches nothing and is denied. Your tool wrapper must set `args.env` from the real
target, not from model output.

### Multi-agent research team

A planner delegates to a researcher, a writer and a reviewer. `can_delegate_to` and
`max_delegation_depth` control who may start whom; rules use `agent.depth` and
`agent.parent_role`; a run budget is shared across the whole tree. Pair it with
`Guard.delegate` to give each sub-agent an even narrower grant. See the
[README](../../README.md#a-multi-agent-example) for the Python side.

## Writing your own

1. Copy the closest policy and start with `defaults.effect: deny`.
2. Add one `allow` rule per thing the agent must do, as narrow as you can make it.
3. Add `deny` rules for the few things that must never happen. Deny overrides everything.
4. Write test cases first for the calls that should be refused, then for the ones that should work.
5. Run `castellan test` and `castellan lint` in CI.

## Pitfalls

- **A rule you expect to match, does not.** Run `castellan explain` to see every rule that was
  considered and why it matched or not.
- **Conditions on missing arguments are false.** `args.amount: {lte: 1000}` is false when there
  is no `amount`, so the call falls through to the default. That is the safe direction.
- **Tool globs.** `*` matches within one dotted segment, `**` crosses dots. `github.*` does not
  match `github.repos.delete`; `github.**` does.
- **Arguments chosen by the model are untrusted.** A condition on an argument is only as strong
  as the code that fills that argument in.

## Where next

- [Docs site](https://kachhadiyahiren.github.io/agent-castellan/): the full policy language reference.
- [Multi-agent example](../multi_agent_team/README.md): a complete team wired to a policy.
- [CONTRIBUTING.md](../../CONTRIBUTING.md): add a policy to this cookbook.
