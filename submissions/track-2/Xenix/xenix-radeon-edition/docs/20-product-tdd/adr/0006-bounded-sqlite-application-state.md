# ADR 0006: Use SQLite for bounded local application state

- Status: accepted
- Date: 2026-07-11
- Supersedes: [ADR 0002](0002-sqlite-for-local-state.md)
- Complements: [ADR 0003](0003-filesystem-for-datasets-models-results.md)

## Context

ADR 0002 limited SQLite to metadata and coordination. The native app also persists
bounded conversation, provider/tool, selection, and recovery state. The old wording
no longer describes the realized boundary.

## Decision

Use SQLite for bounded, queryable local application state. Keep full datasets,
trained-analyzer binaries, exports, logs, caches, and other large or binary content
on the filesystem.

Source, migrations, and tests own schema mechanics.

## Consequences

- Local work remains queryable without a separate database service.
- Backups may include user-authored conversation content.
- Services coordinate database references with filesystem-owned bytes.
- Schema evolution remains migration-controlled.
