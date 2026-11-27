# Policy language reference

*Who this page is for:* anyone writing or reviewing a policy file. *After reading it* you will know every key Castellan accepts, how rules match calls, what each operator does, and how to fix each load-time error. For a gentler introduction, read [writing policies](../guides/writing-policies.md) first.

A policy is one YAML document. Castellan loads it with `castellan` commands or `Guard.from_file`, validates it, and compiles every condition once, so evaluating a call does no parsing. Unknown keys are errors everywhere, so a typo never silently disables a rule.

## Document structure

```yaml
version: 1          # required in practice; must be 1
defaults: {}        # what happens when no rule matches
agents: {}          # roles and who may delegate to whom
rules: []           # the allow / deny / ask rules
budgets: {}         # tool-call and cost limits
approvals: {}       # approval settings
audit: {}           # audit log location
```

### Top-level keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `version` | integer | `1` | Policy language version. The only accepted value is `1`. |
| `defaults` | mapping | `effect: deny` | Fallback behaviour. |
| `agents` | mapping of role name to settings | `{}` | Declares roles. A role with no settings can be written `researcher: {}` or left empty. |
| `rules` | list of rules | `[]` | The rules, in file order. |
| `budgets` | mapping | no limits | Usage limits. |
| `approvals` | mapping | `ttl_seconds: 600` | Approval settings. |
| `audit` | mapping | `path: ./castellan-audit.jsonl` | Audit log settings. |

### `defaults`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `effect` | `deny`, `ask` or `allow` | `deny` | Effect for a call that no rule matches. Keep `deny`; `allow` makes the linter warn (`L007`). |

### `agents.<role>`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `can_delegate_to` | list of role names | `[]` | Roles this role may create with `Guard.delegate`. |
| `max_delegation_depth` | integer ≥ 0 | no limit | A child created by this role must have `depth <= max_delegation_depth`. The root agent has depth 0, so `1` allows children but no grandchildren through this role. |

### `rules[]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | required | Unique, non-blank name. Appears in decisions, traces, audit entries and error messages. |
| `description` | string | none | Free-text note for humans. Not used in decisions. |
| `agents` | list of role names | `["*"]` | Roles the rule applies to. `*` means every role. Must not be empty. |
| `tools` | list of tool globs | `["*"]` | Tools the rule applies to. Must not be empty. See [matching](#matching). |
| `when` | condition | none | Extra condition on the call. Omitted means "always". See [conditions](#conditions-when). |
| `effect` | `allow`, `deny` or `ask` | required | What to do when the rule matches. |
| `reason` | string | none | Message returned in the decision. Without it the reason is `rule '<id>' matched`. |
| `approver` | `human`, `role:<role>` or `agent:<id>` | `human` | Who may approve an `ask`. Ignored for `allow` and `deny`. |
| `priority` | integer | `0` | Chooses which matching rule is *named* when several have the same effect. Higher wins, then earlier in the file. It never lets an allow beat a deny. |

`line` is reserved: writing it in a rule is an error.

### `budgets`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `run.max_tool_calls` | integer ≥ 0 | none | Maximum allowed calls in one run, across all agents. |
| `run.max_cost_units` | number ≥ 0 | none | Maximum summed `cost_units` in one run. |
| `per_role.<role>.max_tool_calls` | integer ≥ 0 | none | Maximum allowed calls per agent of that role. |
| `per_role.<role>.max_cost_units` | number ≥ 0 | none | Maximum cost units per agent of that role. |

See [budgets](../guides/budgets.md) for how counting works.

### `approvals`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `ttl_seconds` | integer > 0 | `600` | How long an approval request stays valid. |

### `audit`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `path` | string | `./castellan-audit.jsonl` | Where `Guard` writes the audit log. A relative path is relative to the process's working directory. |

## Matching

A rule matches a call when **all three** hold: the caller's role is in `agents`, the tool name matches a pattern in `tools`, and `when` (if present) is true.

### Roles

`agents` is a list of exact role names. `["*"]` (or omitting the key) matches every role. Role names are case-sensitive.

### Tool names and globs

Castellan lower-cases tool names before matching, so write patterns in lower case. A pattern matches the *whole* name.

| Pattern part | Matches |
|---|---|
| a literal character | itself |
| `*` | any run of characters **except `.`** |
| `**` | any run of characters, including `.` |
| the whole pattern `*` | every tool |

`?` and `[...]` have no special meaning in tool patterns; they are matched literally.

| Pattern | Matches | Does not match |
|---|---|---|
| `fs.read` | `fs.read` | `fs.read.all` |
| `fs.*` | `fs.read`, `fs.write` | `fs.a.b` |
| `fs.**` | `fs.read`, `fs.a.b` | `web.search` |
| `*.read` | `fs.read`, `db.read` | `fs.a.read` |
| `mcp:filesystem/*` | `mcp:filesystem/read_file` | `mcp:github/read_file` |

Tools from an MCP server are named `mcp:<server>/<tool>`. Because `*` stops only at a dot, `mcp:filesystem/*` also matches `mcp:filesystem/a/b`.

## Conditions (`when`)

A `when` block is **data**. Castellan compiles it into closures and never passes anything to `eval`.

### Shape

A condition is a mapping. Its entries are either *leaf tests* (`path: {operator: operand}`) or *combinators* (`all`, `any`, `not`). Every entry of one mapping must hold (an implicit AND).

```yaml
when:
  args.amount: { gt: 0, lte: 100 }     # two operators on one path: both must hold
  args.currency: { in: [USD, EUR] }    # a second entry: this must hold too
```

### Combinators

| Combinator | Operand | True when |
|---|---|---|
| `all` | non-empty list of conditions | every condition is true |
| `any` | non-empty list of conditions | at least one condition is true |
| `not` | one condition (a mapping) | the condition is false |

They nest to any depth:

```yaml
when:
  all:
    - args.env: { eq: prod }
    - not:
        args.dry_run: { eq: true }
```

### Paths

A path is a dotted lookup into the **evaluation context**. It must start with one of these roots.

| Path | Value |
|---|---|
| `agent.id` | The agent's id. |
| `agent.role` | The agent's role. |
| `agent.depth` | Delegation depth; the root is 0. |
| `agent.parent_role` | Role of the delegating agent. Missing for a root agent. |
| `agent.on_behalf_of` | End-user id. Missing when none was given. |
| `tool.name` | Normalized tool name. |
| `tool.namespace` | The part of the name before the first `.` or `:`; `mcp:server` for MCP tools. |
| `args.<key>[.<key>…]` | A (nested) argument of the call. List items are indexed by number: `args.items.0.name`. |
| `run.id` | The run id. |
| `run.tool_calls` | Calls made so far in the run. See the note below. |
| `time.hour_utc` | Current hour in UTC, 0–23. |
| `time.weekday` | Current weekday, 0 = Monday. |

The `agent`, `tool`, `run` and `time` roots accept only the keys above; anything else is a load-time error.

!!! warning "`run.tool_calls` with `Guard.from_file`"
    A policy engine only knows the run's call count if it is given a counter. `Guard.from_file` does not wire one yet, so `run.tool_calls` is always `0` there. Use `budgets.run.max_tool_calls` to limit a run today.

### Missing paths

If a path does not exist in the context, **every operator is false**, including `ne` and `not_in`. The single exception is `exists: false`, which is true. A call therefore cannot dodge a check by omitting an argument. Use `not:` if you want "absent or different".

### Operators

Every operator below was run against the example shown (the check script is [`operators_check.py`](../examples/operators_check.py)). "Non-matching" shows a value for which the test is false.

| Operator | Operand | Meaning | Example | Matches | Non-matching |
|---|---|---|---|---|---|
| `eq` | scalar | equal; a boolean never equals a number | `args.env: { eq: prod }` | `prod` | `staging` |
| `ne` | scalar | not equal (false if the path is missing) | `args.env: { ne: prod }` | `staging` | `prod` |
| `in` | list of scalars | value is one of the items | `args.currency: { in: [USD, EUR] }` | `EUR` | `GBP` |
| `not_in` | list of scalars | value is none of the items | `args.region: { not_in: [cn, ru] }` | `de` | `ru` |
| `lt` | number | less than | `args.amount: { lt: 100 }` | `99.5` | `100` |
| `lte` | number | less than or equal | `args.amount: { lte: 100 }` | `100` | `"100"` (a string) |
| `gt` | number | greater than | `args.amount: { gt: 0 }` | `1` | `0` |
| `gte` | number | greater than or equal | `args.amount: { gte: 18 }` | `18` | `17` |
| `glob` | string | path-style glob, see below | `args.path: { glob: "/workspace/**" }` | `/workspace/src/app.py` | `/workspace/../etc/passwd` |
| `regex` | string | Python `re.fullmatch`; pattern at most 512 characters | `args.query: { regex: "(?i)select .*" }` | `SELECT 1` | `drop table x; select 1` |
| `contains` | scalar | substring of a string, or element of a list | `args.tags: { contains: urgent }` | `["urgent", "ops"]` | `["ops"]` |
| `starts_with` | string | string prefix | `args.url: { starts_with: "https://api.example.com/" }` | `https://api.example.com/v1` | `http://api.example.com/v1` |
| `ends_with` | string | string suffix | `args.path: { ends_with: ".md" }` | `/workspace/README.md` | `/workspace/app.py` |
| `exists` | boolean | path is present (`true`) or absent (`false`) | `args.token: { exists: false }` | no `token` argument | `token: x` |
| `len_lte` | integer ≥ 0 | string or list length at most | `args.content: { len_lte: 5 }` | `hello` | `hello!` |
| `len_gte` | integer ≥ 0 | string or list length at least | `args.items: { len_gte: 2 }` | `[1, 2]` | `[1]` |

Type rules worth knowing:

- Numeric operators are false for strings and for booleans: `"100"` is not `100`, and `true` is not `1`.
- `regex` must match the **whole** value. To match anywhere, write `.*pattern.*`.
- `in` and `not_in` take a list of scalars (strings, numbers, booleans, null).

#### `glob` in conditions

`glob` is for paths:

| Pattern part | Matches |
|---|---|
| `*` | any run of characters except `/` |
| `?` | one character except `/` |
| `**` | any run of characters including `/` |
| `**/` | zero or more whole directories |

Before matching, any value that contains a `/` has its `.` and `..` segments resolved and repeated slashes collapsed. So `/workspace/../etc/passwd` is tested as `/etc/passwd`, and `"/workspace/**"` does not match it. `**/.env*` matches `/.env`, `/a/b/.env` and `/a/b/.env.local`.

Note the difference: in *tool* patterns `*` stops at `.`; in `glob` conditions `*` stops at `/`.

## Call normalization

Before any rule is looked at, Castellan normalizes the call. The normalized call is what rules see and what the audit log records.

| Part | What happens |
|---|---|
| Tool name | Stripped and lower-cased (with Unicode compatibility folding). Empty names, names over 256 characters and names with spaces or control characters are invalid. `mcp:` names must look like `mcp:<server>/<tool>`. |
| Path arguments | Applies to keys `path`, `file`, `filename`, `filepath`, `dir`, `directory`, `cwd`, `target`, `source`, `dest`, `destination`, and any key ending in `_path`. `.` and `..` are resolved lexically; NUL bytes are rejected; a path that climbs above `/` is rejected. |
| URL arguments | Applies to keys `url`, `uri`, `endpoint` and any key ending in `_url`. Scheme and host are lower-cased, default ports are dropped and internationalized host names are converted to ASCII. |
| Arguments overall | Must be JSON-serializable (string keys, finite numbers), nested at most 32 levels, at most 1 MiB. |

A call that fails normalization is denied with reason `invalid_call`, and the trace says why:

```bash
castellan explain team.yaml --role coder --tool "mcp:bad"
```

```text
DENY rule=- source=invalid reason=invalid_call
                                  Rule trace                                   
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Rule        ┃ Matched ┃ Detail                                              ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ <normalize> │ no      │ MCP tool names must look like 'mcp:<server>/<tool>' │
└─────────────┴─────────┴─────────────────────────────────────────────────────┘
```

## Approver values

| Value | Who may approve |
|---|---|
| `human` | Anyone other than the agent that asked. This is the default. |
| `role:<role>` | An agent of that role in the same run. |
| `agent:<id>` | Exactly that agent id. |

An agent can never approve its own request. The value must match `human`, `role:<role>` or `agent:<id>` exactly.

!!! warning "Known limitation: `role:` approvers"
    `Guard.approve` does not yet tell the approval store which role the approver has, so a request whose approver is `role:<role>` stays pending when answered through the guard. `human` and `agent:<id>` approvers work. Until this is fixed, prefer those two.

## Errors and how to fix them

Every load-time problem raises `PolicyError`, and the CLI prints it as `error: <file>:<line> [rule '<id>':] <message>` with exit code 3. The line points at the offending key. Each message below was produced by loading a small broken file.

| Message | Cause | Fix |
|---|---|---|
| `p.yaml:1 version: Input should be 1` | `version` is not `1`. | Write `version: 1`. |
| `p.yaml:2 unknown key 'rulez'` | A misspelled or unsupported key. | Fix the spelling. Valid keys are on this page. |
| `p.yaml:5 rule 'a': rules.0.effect: Input should be 'allow', 'deny' or 'ask'` | `effect` has another value. | Use `allow`, `deny` or `ask`. |
| `p.yaml:3 rule 'a': rules.0.effect: Field required` | A rule has no `effect`. | Add one. |
| `p.yaml:5 rule 'a': unknown operator 'lessthan' for 'args.path'` | Operator name is not in the table above. | Use a listed operator (`lt`, `lte`, `gt`, `gte`, …). |
| `p.yaml:5 rule 'a': operator 'lte' for 'args.amount' expects a number operand, got '100'` | The operand has the wrong type (here a quoted string). | Write `lte: 100`, without quotes. |
| `p.yaml:5 rule 'a': operator 'in' for 'args.path' expects a list operand, got '/a'` | `in` and `not_in` need a list. | Write `in: [/a]`. |
| `p.yaml:5 rule 'a': operator 'exists' for 'args.path' expects a bool operand, got 'yes please'` | `exists` takes `true` or `false`. | Use a boolean. |
| `p.yaml:5 rule 'a': unknown path 'path': must start with one of agent, args, run, time, tool` | A path with no valid root. | Use `args.path`, not `path`. |
| `p.yaml:5 rule 'a': unknown path 'agent.name': expected one of agent.depth, agent.id, agent.on_behalf_of, agent.parent_role, agent.role` | A key that does not exist under a fixed root. | Pick one of the listed keys. |
| `p.yaml:5 rule 'a': invalid regular expression '(': missing ), unterminated subpattern at position 0` | The pattern does not compile. | Fix the regular expression. |
| `p.yaml:5 rule 'a': 'any' must be a non-empty list of conditions` | `all` or `any` is empty or not a list. | Give it at least one condition. |
| `p.yaml:6 rule 'a': rules.0.approver: Value error, approver must be 'human', 'role:<role>' or 'agent:<id>'` | Bad approver value. | Use one of the three forms. |
| `p.yaml:4 rule 'a': rules.0.tools: Value error, must be a non-empty list of non-empty strings` | `tools` (or `agents`) is empty. | List at least one pattern, or omit the key for "all". |
| `p.yaml:3 defaults.effect: Input should be 'allow', 'deny' or 'ask'` | Bad default. | Use a valid effect. |
| `p.yaml:4 budgets.run.max_tool_calls: Input should be greater than or equal to 0` | Negative limit. | Use a non-negative number. |
| `p.yaml:3 approvals.ttl_seconds: Input should be greater than 0` | Zero or negative lifetime. | Use a positive number of seconds. |
| `p.yaml:6 found duplicate key "id" with value "b" (original value: "a")` | A key appears twice in one mapping. | Remove the duplicate. |
| `p.yaml:6 expected <block end>, but found '?'` | YAML indentation or syntax error. | Fix the indentation near that line. |
| `p.yaml:1 policy document must be a mapping` | The file is a list or a scalar. | Start with `version: 1` and mappings. |
| `nonexist.yaml cannot read policy file: [Errno 2] No such file or directory: 'nonexist.yaml'` | The file path is wrong. | Check the path. |

Duplicate rule **ids** are not a load error. They load fine and the linter reports them as [`L002`](../guides/testing-and-linting.md#l002-duplicate-rule-id).

## Pitfalls

- **Quoted numbers.** `lte: "100"` is a string and is rejected at load time; `args.amount: "100"` at run time is a string and fails every numeric test.
- **Forgetting that missing means false.** `args.env: { ne: prod }` is false when `env` is absent.
- **Trusting argument names.** Normalization only knows the path and URL keys listed above.
- **Relying on order.** Rule order never changes the effect; only [`priority`](#rules) changes which rule is named.

## Where to go next

- [Writing policies](../guides/writing-policies.md): these keys in context.
- [CLI reference](cli.md): `check`, `explain`, `test`, `lint`.
- [Python API](python-api.md): `load_policy`, `PolicyEngine` and `Guard`.
