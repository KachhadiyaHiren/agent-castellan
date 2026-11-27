# Contributing to Castellan

Thanks for helping. **Audience:** you want to fix a bug, add a feature or improve the docs.
After this guide you can set up the project, find your way around the code, make the three most
common kinds of change (operator, lint rule, integration) and get a pull request merged.

[docs/CONVENTIONS.md](docs/CONVENTIONS.md) holds the short rule list for code, tests and git;
[PLAN.md](PLAN.md) holds the design. Read the policy and decision sections of PLAN.md before
changing engine behaviour.

## Development setup

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/KachhadiyaHiren/agent-castellan.git
cd agent-castellan
uv sync --all-extras
uv run pre-commit install   # optional: ruff on every commit
```

Before you open a pull request, all of these must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run castellan test examples/policies/tests/*.test.yaml
```

## Project layout

| Path | What lives there |
|---|---|
| `src/agent_castellan/models.py`, `interfaces.py`, `errors.py` | Shared data models, component protocols and exceptions. Changing these affects everything: discuss in an issue first. |
| `guard.py` | `Guard`, the one entry point: budgets, policy, grants, approvals, audit. |
| `policy/` | YAML loader (`loader.py`, `schema.py`), condition DSL (`conditions.py`), call normalization (`normalize.py`), glob matching and the `PolicyEngine`. |
| `delegation/` | Grants, chained HMAC signatures, attenuation checks, token encoding. |
| `runtime/` | Approval stores and budget trackers (memory and SQLite). |
| `audit/` | Hash-chained audit log and verification. |
| `analysis/lint.py` | Policy lint checks (L001-L007). |
| `cli/` | The `castellan` commands (Typer). |
| `integrations/` | `@guarded`, the MCP proxy, the LangGraph wrapper. |
| `testing/fakes.py` | In-memory fakes for unit tests. |
| `tests/unit/` | Mirrors `src/`: `tests/unit/policy/test_conditions.py` tests `policy/conditions.py`. |
| `examples/policies/` | The tested policy cookbook. |
| `docs/site/`, `mkdocs.yml` | The documentation site. |

## How to add a condition operator

Operators are the `eq`, `glob`, `regex` ... keys inside a `when` block. They live in
`src/agent_castellan/policy/conditions.py`.

1. **Write the test first** in `tests/unit/policy/test_conditions.py`: a case that matches, one
   that does not, one with a wrong operand type (a load-time error), and one where the path is
   missing (every operator is false for a missing path, except `exists: false`).
2. **Add the predicate builder** next to the others, for example
   `def _op_not_starts_with(operand: Any) -> Predicate`. It receives the operand from the YAML and
   returns a function over the looked-up value. Return `False` for a value of the wrong type.
3. **Register it** by adding an `OperatorSpec(name, operand_type, description, builder, validator)`
   to the `OPERATORS` table. The validator rejects a bad operand at load time, which produces an
   error with the file, line and rule id.
4. **Document it**: add it to the operator table in the policy language reference under
   `docs/site/` and to section 3.2 of PLAN.md if the change is meant to be permanent.
5. Run the checks above and add a `CHANGELOG.md` line.

Operators must be pure and fast, must never call `eval`, and regular expressions must be compiled
at load time with a bounded length.

## How to add a lint rule

Lint checks live in `src/agent_castellan/analysis/lint.py` and are shown by `castellan lint`.

1. **Pick the next id** (the last is `L007`) and a severity: `error` makes `castellan lint` exit 1,
   `warning` does not. Prefer `warning` unless the policy is certainly broken.
2. **Write the test first** in `tests/unit/analysis/test_lint.py`, using the `rule()` and `pol()`
   helpers: one policy that triggers the check and one clean policy that must not.
3. **Implement** a function `_check_<name>(policy) -> list[Finding]`. Include the rule id and
   `rule.line` in each `Finding` so the CLI can point at the line.
4. **Call it** from `lint_policy`.
5. **Document** the new id, what it means and how to fix it in the testing-and-linting page of the
   docs site, and update the `--help` text in `cli/lint.py` (it names the id range).
6. Run `castellan lint` on every file in `examples/policies/`: none may start producing findings.

## How to add an integration

An integration turns a framework's "about to call a tool" hook into `guard.authorize`.
`integrations/decorator.py` is the smallest complete example.

1. **Write the test first** in `tests/unit/integrations/`, using the fixtures in its `conftest.py`.
   Cover: allowed call runs, denied call raises `PermissionDenied` and the tool body does not run,
   an `ask` decision raises `ApprovalRequired` with the approval id.
2. **Create a module** in `src/agent_castellan/integrations/`. Build a `ToolCall(tool=..., args=...)`
   from the framework's call, pass the acting `Principal` and its grant chain to
   `integrations.decorator.enforce`, and only then run the tool. Fail closed: if no principal is
   available, raise instead of allowing.
3. **Keep the framework optional.** Import it inside the module and add it as an extra in
   `pyproject.toml` (like `mcp` and `langgraph`). The core package must import without it.
4. **Document** it on the integrations page with a complete example.

## Adding a cookbook policy

Put the policy in `examples/policies/`, a test file in `examples/policies/tests/` named
`<policy>.test.yaml`, and a paragraph in `examples/policies/README.md`. Start with a header comment
describing the scenario, comment every rule with why it exists, and test the calls that must be
refused as well as the ones that must work. `castellan lint` must report nothing.

## Commit style

- [Conventional Commits](https://www.conventionalcommits.org/): `feat(policy): add regex operator`,
  `fix(cli): exit 3 on unreadable policy`, `docs: explain approvals`, `test(delegation): ...`.
- Keep commits small, each one green. A commit message describes the change and nothing else.
- Add one line to `CHANGELOG.md` under `Unreleased`.
- Branch names: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`.

## How reviews work

1. Open a pull request using the template and keep it focused on one change.
2. CI runs lint, types and tests on Linux and macOS across Python 3.11-3.13. It must be green.
3. A maintainer reviews for correctness first (especially anything touching decisions, grants,
   approvals or the audit chain), then tests, then docs and naming. Expect questions rather than
   orders; reply in the thread.
4. Security-sensitive changes (anything that can turn a deny into an allow) need a test that
   shows the old behaviour was wrong and a note in the pull request explaining the reasoning.
5. When approved and green, a maintainer merges.

Security issues: follow [SECURITY.md](SECURITY.md), not a public issue. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

By contributing you agree that your contribution is licensed under Apache-2.0.
