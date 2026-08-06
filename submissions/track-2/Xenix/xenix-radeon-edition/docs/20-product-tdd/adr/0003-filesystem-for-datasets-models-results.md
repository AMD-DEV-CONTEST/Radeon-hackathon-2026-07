# ADR 0003: Keep datasets, models, and results on the local filesystem

- Status: accepted
- Date: 2026-03-09

## Context

Native workflows center on user-selected local data and user-openable outputs. Datasets, trained models, and model apply results can be large, binary, and easier to manage as files than as database blobs.

## Decision

Persist datasets, model artifacts, exports, and logs on the local filesystem. Use SQLite only to reference and describe those artifacts.

## Consequences

- Users can inspect outputs directly with local tools.
- The app can avoid expensive blob handling inside SQLite.
- Services must define stable storage paths and ownership rules.
- Deletion and cleanup logic must distinguish user-owned inputs from app-owned outputs.
