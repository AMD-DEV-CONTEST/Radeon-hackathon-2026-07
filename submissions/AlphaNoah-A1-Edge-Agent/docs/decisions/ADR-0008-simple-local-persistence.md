# ADR-0008: Use SQLite for Local Persistence

## Status

Accepted and implemented — 2026-07-23

## Context

The demo needs restart recovery, unique IDs, trace reconstruction and isolated test data without distributed infrastructure.

## Decision

Use Python's built-in `sqlite3`:

- separate tables for each persisted core object;
- one `trace_id` for the event lifecycle;
- transactional Event status + AuditRecord;
- idempotency keys for evidence submission;
- one explicitly selected database per demo or test;
- `.sqlite` files excluded from Git.

## Consequences

- There is no third-party database dependency.
- Program restart recovery is tested.
- Multi-node scaling, migrations and production backup remain out of scope.
