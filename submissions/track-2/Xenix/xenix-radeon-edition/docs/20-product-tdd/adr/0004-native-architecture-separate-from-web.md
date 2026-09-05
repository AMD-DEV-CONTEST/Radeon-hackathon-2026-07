# ADR 0004: Do not reuse the current web frontend-backend layering

- Status: accepted
- Date: 2026-03-09
- Clarified by: [ADR 0007](0007-remote-integrations-remain-adapters.md)

## Context

The existing web application uses browser and backend deployment concerns that do not map directly to a single-process desktop app. Issue `#46` explicitly creates a separate `native` branch with a reduced product surface.

## Decision

Use a native-specific layered architecture: Qt Widgets UI, local services, ML adapters, SQLite metadata, and filesystem artifacts. Do not mirror the current web frontend-backend split inside the desktop shell.

## Consequences

- Native code can optimize for direct local orchestration instead of HTTP boundaries.
- The repo stays smaller and easier to reason about during the first native milestone.
- Shared logic, if any, should be copied intentionally only when it is truly portable.
- Reintroducing remote APIs or deployment-style boundaries requires a new ADR.
