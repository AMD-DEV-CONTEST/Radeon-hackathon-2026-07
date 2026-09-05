# ADR 0007: Keep remote integrations as adapters

- Status: accepted
- Date: 2026-07-11
- Clarifies: [ADR 0004](0004-native-architecture-separate-from-web.md)
- Relates to: [ADR 0005](0005-ssh-ml-worker-pool.md)

## Context

ADR 0004 rejected web-style frontend/backend layering. Its remote-API wording became
ambiguous after Xenix adopted external LLM providers and SSH execution, neither of
which transfers product authority.

## Decision

Allow outbound provider APIs and remote execution adapters behind local services. A
Xenix-owned remote backend or hosted product authority requires another ADR.

Local services own orchestration; SQLite and local canonical artifacts own state and
results. Provider and worker details remain adapter concerns.

## Consequences

- SSH workers cannot own datasets, models, tasks, or artifacts.
- Remote outputs are finalized locally before success.
- A future Xenix server requires an explicit decision.
