# ADR-0010: Separate the Industrial Agent Core from Domain Skills

## Status

Accepted — 2026-07-23

## Context

AlphaNoah v0.1 has a runnable P0 closed loop, currently validated with a
synthetic Food SOP scenario. Treating that validation scenario as the product
scope would couple the Runtime to one domain and conflict with the hackathon
positioning of AlphaNoah as an industrial field Agent.

The industrial product direction is to lower the reporting barrier for
traditional factory workers through QR-based entry points, use AI to assist
anomaly analysis, and connect responsible people to a traceable handling loop.
QR and model integration are not implemented in v0.1.

## Decision

AlphaNoah Runtime is separated from industry Skills.

Core Runtime is responsible for:

- Event
- Decision
- DecisionHook
- HumanReview
- Task
- Evidence
- Review
- AuditRecord

Industry Skills are responsible for domain-specific input validation, analysis
policy, task templates and review policy. Candidate domains include:

- Food Safety
- Equipment Maintenance
- Quality Inspection
- Safety Inspection

The current Food SOP implementation is the **First validation skill**. It is not
the AlphaNoah product scope. v0.1 does not implement the other candidate Skills.

## Consequences

- Core objects and state transitions remain domain-neutral.
- New domains must reuse the existing Event, Task and AuditRecord models.
- Domain-specific thresholds and SOP logic stay outside the Core Runtime.
- v0.1 keeps one implemented Skill and does not expand several industries in
  parallel.
- QR, AI provider and industrial-system adapters can be added later at explicit
  boundaries without rewriting the Runtime.
- ADR-0006 remains as the record of the bounded first validation scenario and is
  amended by this decision.
