# Python API reference

*Who this page is for:* developers wiring Castellan into agent code. *After reading it* you will know which objects to import, how to authorize a call, and what each class and function promises. The text below is generated from the docstrings in the source, so it always matches the installed version.

## The 30-second tour

Most programs use four things: a `Guard`, a `Principal` for each agent, `ToolCall` objects, and the `Decision` that comes back.

```python
import secrets

from agent_castellan import Effect, Guard, ToolCall

guard = Guard.from_file("first-policy.yaml", key=secrets.token_bytes(32))
planner = guard.start_run("planner", on_behalf_of="alice")

decision = guard.authorize(planner, ToolCall(tool="fs.read", args={"path": "/workspace/app.py"}))
if decision.effect is Effect.ALLOW:
    ...  # run the tool
```

The [getting started](../getting-started.md) page runs a complete version of this, including delegation and approvals, with its real output.

Everything in the first section below is importable straight from `agent_castellan`. The other modules are imported by path.

## Guard

::: agent_castellan.Guard
    options:
      members:
        - from_file
        - start_run
        - delegate
        - authorize
        - check
        - approve

## Values

These immutable [pydantic](https://docs.pydantic.dev) models flow in and out of the guard.

::: agent_castellan.ToolCall

::: agent_castellan.Principal

::: agent_castellan.Decision

::: agent_castellan.TraceStep

::: agent_castellan.Effect

::: agent_castellan.Grant

::: agent_castellan.ApprovalRequest

::: agent_castellan.ApprovalStatus

::: agent_castellan.AuditEntry

## Errors

All Castellan errors derive from `CastellanError`.

::: agent_castellan.CastellanError

::: agent_castellan.PolicyError

::: agent_castellan.GrantError

::: agent_castellan.PermissionDenied

::: agent_castellan.ApprovalRequired

::: agent_castellan.BudgetExceeded

## Loading and evaluating policies

Use these when you only need decisions, without grants, approvals, budgets or auditing.

::: agent_castellan.policy.loader.load_policy

::: agent_castellan.policy.loader.load_policy_text

::: agent_castellan.policy.engine.PolicyEngine
    options:
      members:
        - decide
        - approver_for
        - can_delegate

::: agent_castellan.policy.schema.Policy

::: agent_castellan.policy.schema.Rule

## Decorator integration

::: agent_castellan.integrations.decorator.guarded

::: agent_castellan.integrations.decorator.guard_context

See [integrations](../guides/integrations.md) for the MCP proxy and the LangGraph wrapper.

## Audit log

::: agent_castellan.audit.log.AuditLog
    options:
      members:
        - append

::: agent_castellan.audit.verify.verify_log

::: agent_castellan.audit.verify.VerifyResult

## Linting

::: agent_castellan.analysis.lint.lint_policy

::: agent_castellan.analysis.lint.Finding

## Pitfalls

- **Creating a `Guard` per call.** Build one at start-up and share it. Approvals and budgets live inside it (or in its SQLite state file).
- **Ignoring `ask`.** `authorize` returns a `Decision` and does not raise. If you treat anything but `deny` as success you will run calls that still need approval. Check `decision.effect is Effect.ALLOW`, or use `@guarded`, which raises for you.
- **Random keys across processes.** Pass the same `key=` (or `CASTELLAN_KEY`) to every process that creates or verifies grants.
- **Calling `check` instead of `authorize`.** `check` is a dry run and leaves no audit entry.

## Where to go next

- [Concepts](../concepts.md): what each model means.
- [Multi-agent delegation](../guides/delegation.md) and [approvals](../guides/approvals.md).
- [CLI reference](cli.md): the same engine from a terminal.
