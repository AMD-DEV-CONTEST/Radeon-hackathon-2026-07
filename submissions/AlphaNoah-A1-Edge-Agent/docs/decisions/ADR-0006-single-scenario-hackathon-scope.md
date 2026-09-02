# ADR-0006: Use One Food-SOP Scenario for the Hackathon

## Status

Amended by ADR-0010 — 2026-07-23

## Context

The repository previously described packaging equipment, QR identity, future robots and general enterprise workflows. Building all of them would prevent a verifiable end-to-end prototype.

## Decision

The first validation skill is a synthetic restaurant cold-holding temperature anomaly:

```text
structured observation
→ deterministic analysis
→ human approval
→ corrective task
→ synthetic evidence
→ review
→ closed event and timeline
```

All fixtures state “Synthetic demo data / Not a real production incident.” The demo threshold is not operational guidance.

This choice limits the v0.1 validation path only. It does not define AlphaNoah
as a food-management product; the product scope is an industrial field Agent.

## Consequences

- The P0 runtime has one clear acceptance path.
- Existing equipment/QR/robot material remains an architecture extension.
- Image input, other industries and multiple Skills are not built in parallel.
