# Security Policy

Castellan is an authorization layer, so security reports are taken seriously.

## Supported versions

Until 1.0, only the latest released version receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub:
<https://github.com/KachhadiyaHiren/agent-castellan/security/advisories/new>

Include what you found, how to reproduce it, and the impact you expect. You can expect an
acknowledgement within 7 days. We will agree a disclosure date with you and credit you in the
advisory unless you prefer otherwise.

## Scope

In scope: decision bypasses, grant forgery or widening, approval replay, audit-log tampering that
`castellan audit verify` fails to detect, and path or URL normalization bypasses.

Out of scope: a host process that never calls the guard, and tools that ignore the decision they
are given. See the threat model in the documentation for details.
