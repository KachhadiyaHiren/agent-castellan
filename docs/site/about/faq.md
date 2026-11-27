# FAQ

Short answers, with links to the page that explains more.

## Basics

### What does Castellan do?
It decides, for each tool call an agent makes, whether to **allow**, **deny** or **ask a
person first**, based on a YAML policy. When an agent hands work to another, the second agent
can never get more power than the first. See [Concepts](../concepts.md).

### Is it a sandbox?
No. It is an authorization layer. It says yes or no; your tool code or a real sandbox
(container, restricted user) enforces what the tool can touch. See the
[security model](security.md).

### Does it call a model, or need network access?
No. Decisions are local, deterministic code with no model and no network.

### Which agent frameworks does it work with?
Any MCP client through the [MCP proxy](../guides/integrations.md#mcp-proxy), plain Python
functions through `@guarded`, and LangGraph through `guard_tools`. Anything else can call
`Guard.authorize` directly.

## Policies and decisions

### Why was my call denied?
Run [`castellan explain`](../reference/cli.md) with the same role, tool and arguments. It
prints every rule and why it did or did not match. If the reason is `no rule matched`, the
default `deny` applied.

### I have an `allow` rule and a `deny` rule that both match. Which wins?
`deny`, always. Priority only chooses which rule is named in the result. See
[deny overrides](architecture.md#deny-overrides-everything).

### Can a delegation grant allow something the policy denies?
No. Grants only narrow. The policy and every grant must all allow a call.

### Can I test and lint my policies?
Yes: `castellan test` and `castellan lint`. See
[Testing and linting](../guides/testing-and-linting.md).

## Delegation

### Why can't a child agent ask for more tools?
Because that would let a hijacked agent promote itself. Widening a grant is refused when it is
minted and again when it is verified. See [Delegation](../guides/delegation.md).

### Why does `delegate` fail with "expiry extends past the parent grant's expiry"?
The child's default lifetime (900 s) is longer than what is left on the parent's grant. Pass a
shorter `ttl_seconds`.

### How do I send a grant to another process?
Serialize the chain with `chain_to_token`, send the string, and parse it with
`chain_from_token`. Both processes need the same root key. See
[Passing grants between processes](../guides/delegation.md#passing-grants-between-processes).

### Can I revoke a grant?
Not individually. Grants expire, so keep `ttl_seconds` short, and rotate the root key to
invalidate everything. See [Key management](security.md#key-management).

## Approvals

### What happens when a rule says `ask`?
The call returns `ask` with an `approval_id`. After someone approves it, the agent repeats the
identical call once. See [Approvals](../guides/approvals.md).

### Can an approval be reused?
No. It covers one exact call, once, before it expires.

### Who counts as a human approver?
Whoever your application says. Castellan trusts the `approver_id` you pass; authenticate the
person first.

### Why does a `role:reviewer` approval stay pending?
That is a known limitation in this release; see the
[warning on the Approvals page](../guides/approvals.md#who-can-approve-the-approver-field).

## State, audit and operations

### Do approvals and budgets survive a restart?
Only with `state_path=` (SQLite). Without it they live in memory.

### How do I know the audit log was not edited?
Run `castellan audit verify`. It catches edits, deleted middle entries and reordering, but not
removal of the last entries unless you record the latest hash elsewhere. See
[Audit log](../guides/audit.md#what-the-log-cannot-prove).

### Why does Castellan warn about a random key?
You gave no key and `CASTELLAN_KEY` is unset, so it generated one for this process. Grants will
not verify in other processes. Set `CASTELLAN_KEY` to 64 hex characters.

### How fast is a decision?
Rules compile once at load time, so a decision does no parsing. Design target:
tens of microseconds for a policy of about fifty rules. Measure on your own hardware.

### Does a budget count calls that were denied?
No. Only calls that end up allowed are counted. See [Budgets](../guides/budgets.md).

## Contributing

### How do I add an operator, lint rule or integration?
See [How to extend](architecture.md#how-to-extend) and `CONTRIBUTING.md` in the repository.

### I think I found a security issue.
Please follow `SECURITY.md` in the repository and report it privately.
