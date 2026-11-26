# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

- Add project foundation: core models, component interfaces, `Guard` orchestration, test fakes, CLI skeleton and CI.
- Add delegation: chained-HMAC grants with attenuation checks, conservative glob subsumption, token serialization and `ChainVerifier`.
- Add approval stores and budget trackers (memory and SQLite backends).
- Add hash-chained audit log with verify/tail helpers and policy lint checks L001-L007.
- Add policy engine: YAML loader with line-numbered errors, condition DSL, call normalization and `PolicyEngine`.
