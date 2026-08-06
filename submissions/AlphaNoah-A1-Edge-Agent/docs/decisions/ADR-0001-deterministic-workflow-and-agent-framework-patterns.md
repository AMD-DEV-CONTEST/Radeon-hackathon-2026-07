# ADR-0001: Use a Deterministic Workflow while Adapting LangChain and LangGraph Patterns

> **AlphaNoah A1 Edge Agent** — *An AMD ROCm-powered industrial asset maintenance edge agent.*

## Status

Accepted for hackathon v0.1

Decision date: 2026-07-22<br>
Implementation status: the AlphaNoah-owned deterministic state machine and SQLite
persistence are implemented for the food-SOP demo. LangChain and LangGraph remain
reference-only and are not runtime dependencies.

## Context

The hackathon maintenance workflow is bounded but stateful. It must:

- resolve an asset identity;
- interpret a fault description;
- retrieve local history and simulated guidance;
- create and persist a work order;
- interrupt for human confirmation;
- resume after a decision;
- record a physical repair result;
- verify recovery;
- close, reopen, retry or escalate with an audit trail.

This flow is safety-sensitive and cannot allow an LLM to invent state, execute arbitrary tools or approve its own high-impact recommendation. It needs structured output, durable checkpoints, bounded recovery and behavior that can be tested within a two-week competition schedule.

LangChain and LangGraph expose mature patterns relevant to these concerns. However, adding either runtime to the critical path would also add dependencies, abstractions and integration work before the current local Ollama model's structured tool behavior has been fully measured.

## Decision

A1 v0.1 will not introduce the LangChain or LangGraph runtime as a critical dependency.

The planned lightweight runtime will use:

- a deterministic Python state machine;
- Pydantic schemas for domain and Skill boundaries;
- SQLite for local checkpoints and audit records;
- typed, allow-listed Skills;
- an explicit human-confirmation gate;
- bounded retry;
- stable failure states and error codes;
- auditable guarded transitions.

Domain models remain independent of any orchestration framework. A future framework can enter only through an adapter.

## Patterns Adapted

### From LangChain patterns

- Typed Tools → typed A1 Skill manifests and input/output contracts;
- Structured Output → schema-constrained Incident, Assessment and Experience drafts;
- Schema Validation → model results rejected before deterministic use when invalid;
- Bounded Retry → one format-repair retry rather than open-ended model loops;
- model/tool separation → model proposes; deterministic code performs stateful effects.

### From LangGraph patterns

- Explicit State → persisted work-order and task state;
- Node/Transition → named Skill step and guarded transition;
- Checkpoint → SQLite state saved before interruption or external wait;
- Interrupt/Resume → explicit `waiting_information` and `waiting_confirmation` states;
- Human Approval → persisted approval object with actor, action and expiry;
- Conditional Recovery → deterministic reopen, retry or escalation branches.

The accurate attribution is:

```text
Inspired by LangChain and LangGraph patterns
```

It is not:

```text
Built with LangChain or LangGraph
```

## Reasons

- fewer dependencies and a smaller failure surface;
- predictable state transitions and explicit invariants;
- easier audit, unit testing and demonstration;
- easier debugging with the current local Ollama path;
- no requirement for the local model to produce native framework tool calls;
- clearer visibility of AlphaNoah's own maintenance Runtime;
- more controllable scope within two weeks.

## Consequences

Positive consequences:

- domain records and state rules remain portable;
- every high-impact effect has a deterministic guard;
- the demo can explain exactly why a transition occurred;
- a model or Provider can be replaced without changing workflow truth.

Negative consequences:

- the project must maintain its own transition table and invariants;
- checkpoint, resume, idempotency and compensation need explicit tests;
- custom observability is required;
- adding many branches or concurrent Skills could make the lightweight scheduler expensive to maintain.

Therefore the hackathon workflow must remain small: one simulated asset scenario, one approval gate, one verification loop and bounded recovery.

## Future Migration Criteria

Formally evaluate LangGraph or another orchestration runtime only when one or more of these become real requirements:

- work orders run across days rather than a short demo session;
- multiple asynchronous approval points are required;
- precise recovery after service restart becomes operationally complex;
- several Skills need concurrent execution and join semantics;
- compensation or rollback graphs become non-trivial;
- workflow branches materially exceed a maintainable transition table;
- visual workflow operations are required;
- maintaining the custom state machine costs more than an adapter migration;
- a proof confirms the framework works with the pinned local Provider and preserves domain independence.

Migration requires an ADR, contract tests, checkpoint compatibility plan and rollback path. Framework types must not leak into `Asset`, `Incident`, `WorkOrder`, `SkillCommand`, `SkillStatus`, `Approval`, `VerificationResult`, `MemoryRecord`, `EventImportance`, `ExperienceSummary`, `ExecutionEvidence` or `FailureMode`.

## Alternatives Considered

### Adopt LangGraph immediately

Deferred. Its persistence and interrupt patterns are relevant, but current scope does not justify integration risk before the core local path exists.

### Adopt LangChain agents immediately

Rejected for the critical path. An unconstrained agent/tool loop is less predictable than the small maintenance state machine and is not needed for the demo.

### Use only a single prompt with no state machine

Rejected. It cannot safely represent approval, verification, reopen, idempotency or auditable failure recovery.

## References

- See [External Technical References](../references/REFERENCES.md) for verified official LangChain and LangGraph documentation links and the dependency boundary.
- See [Design Inspirations](../research/DESIGN_INSPIRATIONS.md) for the attribution boundary.
