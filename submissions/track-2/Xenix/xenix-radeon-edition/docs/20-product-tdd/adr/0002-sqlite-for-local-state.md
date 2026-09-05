# ADR 0002: Use SQLite for local metadata and task state

- Status: superseded by [ADR 0006](0006-bounded-sqlite-application-state.md)
- Date: 2026-03-09

## Context

The native app needs local persistence for task bookkeeping, model metadata, and lightweight configuration without introducing a separate service process. The app runs in single-user local mode.

## Decision

Use SQLite for small, queryable local state. Keep it limited to metadata and coordination records.

## Consequences

- The app avoids operating a separate database service.
- Local state can be inspected and backed up as a single file when needed.
- SQLite schema changes must be managed carefully through migrations and service-owned access.
- Large artifacts remain outside the database.
