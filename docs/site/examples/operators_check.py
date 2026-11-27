"""Evaluates every example in the policy-language reference and prints PASS/FAIL."""

from agent_castellan.policy.conditions import compile_condition

CASES = [
    # (condition, context args, expected)
    ({"args.env": {"eq": "prod"}}, {"env": "prod"}, True),
    ({"args.env": {"eq": "prod"}}, {"env": "staging"}, False),
    ({"args.env": {"ne": "prod"}}, {"env": "staging"}, True),
    ({"args.env": {"ne": "prod"}}, {}, False),  # missing path: always false
    ({"args.currency": {"in": ["USD", "EUR"]}}, {"currency": "EUR"}, True),
    ({"args.currency": {"in": ["USD", "EUR"]}}, {"currency": "GBP"}, False),
    ({"args.region": {"not_in": ["cn", "ru"]}}, {"region": "de"}, True),
    ({"args.region": {"not_in": ["cn", "ru"]}}, {"region": "ru"}, False),
    ({"args.amount": {"lt": 100}}, {"amount": 99.5}, True),
    ({"args.amount": {"lt": 100}}, {"amount": 100}, False),
    ({"args.amount": {"lte": 100}}, {"amount": 100}, True),
    ({"args.amount": {"lte": 100}}, {"amount": "100"}, False),  # a string is not a number
    ({"args.amount": {"lte": 100}}, {"amount": True}, False),  # a bool is not a number
    ({"args.amount": {"gt": 0}}, {"amount": 1}, True),
    ({"args.amount": {"gt": 0}}, {"amount": 0}, False),
    ({"args.amount": {"gte": 18}}, {"amount": 18}, True),
    ({"args.amount": {"gte": 18}}, {"amount": 17}, False),
    ({"args.path": {"glob": "/workspace/**"}}, {"path": "/workspace/src/app.py"}, True),
    ({"args.path": {"glob": "/workspace/**"}}, {"path": "/workspace/../etc/passwd"}, False),
    ({"args.path": {"glob": "/workspace/*"}}, {"path": "/workspace/src/app.py"}, False),
    ({"args.path": {"glob": "**/.env*"}}, {"path": "/.env"}, True),
    ({"args.path": {"glob": "**/.env*"}}, {"path": "/a/b/.env.local"}, True),
    ({"args.query": {"regex": "(?i)select .*"}}, {"query": "SELECT 1"}, True),
    ({"args.query": {"regex": "(?i)select .*"}}, {"query": "drop table x; select 1"}, False),
    ({"args.tags": {"contains": "urgent"}}, {"tags": ["urgent", "ops"]}, True),
    ({"args.body": {"contains": "password"}}, {"body": "my password is"}, True),
    ({"args.body": {"contains": "password"}}, {"body": "hello"}, False),
    (
        {"args.url": {"starts_with": "https://api.example.com/"}},
        {"url": "https://api.example.com/v1"},
        True,
    ),
    (
        {"args.url": {"starts_with": "https://api.example.com/"}},
        {"url": "http://api.example.com/v1"},
        False,
    ),
    ({"args.path": {"ends_with": ".md"}}, {"path": "/workspace/README.md"}, True),
    ({"args.token": {"exists": False}}, {}, True),
    ({"args.token": {"exists": False}}, {"token": "x"}, False),
    ({"args.token": {"exists": True}}, {"token": "x"}, True),
    ({"args.token": {"exists": True}}, {}, False),
    ({"args.content": {"len_lte": 5}}, {"content": "hello"}, True),
    ({"args.content": {"len_lte": 5}}, {"content": "hello!"}, False),
    ({"args.items": {"len_gte": 2}}, {"items": [1, 2]}, True),
    ({"args.items": {"len_gte": 2}}, {"items": [1]}, False),
    ({"args.items.0.name": {"eq": "a"}}, {"items": [{"name": "a"}]}, True),
    # several operators on one path: all must hold
    ({"args.amount": {"gt": 0, "lte": 100}}, {"amount": 50}, True),
    ({"args.amount": {"gt": 0, "lte": 100}}, {"amount": 500}, False),
    # combinators
    ({"all": [{"args.a": {"eq": 1}}, {"args.b": {"eq": 2}}]}, {"a": 1, "b": 2}, True),
    ({"any": [{"args.a": {"eq": 1}}, {"args.b": {"eq": 2}}]}, {"a": 0, "b": 2}, True),
    ({"not": {"args.a": {"eq": 1}}}, {"a": 1}, False),
    ({"not": {"args.a": {"eq": 1}}}, {}, True),  # not of a false (missing) leaf is true
    # two entries side by side: all must hold
    ({"args.a": {"eq": 1}, "args.b": {"eq": 2}}, {"a": 1, "b": 2}, True),
]

failures = 0
for cond, args, expected in CASES:
    got = compile_condition(cond)({"args": args})
    ok = got is expected
    failures += not ok
    print("PASS" if ok else "FAIL", cond, args, "->", got)
print(f"{len(CASES) - failures}/{len(CASES)} examples behave as documented")
raise SystemExit(1 if failures else 0)
