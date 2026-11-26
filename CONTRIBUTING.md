# Contributing to Castellan

Thanks for helping. Please read [docs/CONVENTIONS.md](docs/CONVENTIONS.md) first; it is the
single source of truth for code, tests, git and review rules.

## Setup

```bash
uv sync --all-extras
uv run pre-commit install   # optional: ruff on every commit
```

## Before you open a pull request

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

All four must pass. Write the test first, name it by behaviour, and keep each package at
90% line coverage or better.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat(policy): add regex operator`.
- Keep commits small and each one green.
- Add one line to `CHANGELOG.md` under `Unreleased`.
- Security issues: follow [SECURITY.md](SECURITY.md), not a public issue.

By contributing you agree that your contribution is licensed under Apache-2.0.
