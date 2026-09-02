# ADR-0007: Require Explicit Human Confirmation

## Status

Accepted and implemented — 2026-07-23

## Context

An anomaly analysis must not silently create operational work. A model or rule also must not impersonate a supervisor.

## Decision

- Anomaly Decisions route to `PENDING_HUMAN_REVIEW`.
- Only a non-empty `human:*` actor may create HumanReview.
- Approved, rejected and revised outcomes are persisted.
- Task creation is legal only after an approved Decision.
- Post-task automated review cannot replace the earlier human decision.

## Consequences

- CLI automation requires an explicit `--decision` value or interactive answer.
- Future UI/authentication must preserve the same actor and audit contract.
- Tests cover approval, rejection and illegal pre-approval task creation.
