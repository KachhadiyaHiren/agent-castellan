# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Policy linter:** added check `L008` (warning) for roles defined under `agents` that are never referenced by any rule, approver or `can_delegate_to`.

## [0.1.0] - 2026-11-27

First public release.

### Added

- **Policy engine:** YAML policy language with a data-only condition DSL, tool and agent matching, call normalization (paths, URLs, tool names), deny-overrides decisions and a full decision trace. Load errors report the file, line and rule.
- **Multi-agent delegation:** chained-HMAC grants that can only shrink (tools, conditions, expiry, call limits), token serialization for passing grants between processes, and `ChainVerifier`.
- **Approvals:** `ask` rules routed to a human, a role or a specific agent; approvals bound to the exact call, single-use and expiring. Memory and SQLite backends.
- **Budgets:** limits per run tree, per role, per agent and per grant, with optional cost units. Memory and SQLite backends.
- **Audit log:** append-only, hash-chained JSONL with `verify` that pinpoints the first tampered entry.
- **Policy tooling:** lint checks L001–L007 and policy unit tests.
- **CLI:** `castellan check`, `explain`, `test` (with JUnit output), `lint` (text, JSON and GitHub annotations), `audit verify|tail`, `approve list|accept|reject` and `mcp-proxy`.
- **Integrations:** `@guarded` decorator with `guard_context`, a stdio MCP proxy that enforces policy on `tools/call`, and a LangGraph `guard_tools` wrapper.
- **Examples:** a four-agent reference team (planner, researcher, coder, reviewer) with six scenarios and a walkthrough, and a cookbook of ten commented policies with tests.
- **Documentation:** a full documentation site covering getting started, concepts, guides, reference, security model and architecture.

[Unreleased]: https://github.com/KachhadiyaHiren/agent-castellan/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KachhadiyaHiren/agent-castellan/releases/tag/v0.1.0
