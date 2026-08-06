# Implementation Taste

Implementation taste guides non-trivial code design and implementation. It is language- and stack-neutral, not a style guide, pattern catalog, or mandatory phase.

Load it when a change shapes structure, boundaries, data, state, authority, durable naming, abstraction, performance, or complexity. Skip it for mechanical edits whose owner and verification are already clear.

## Preserve One Authority

Every durable fact, state, relationship, and decision needs one authority. Treat replicas, caches, views, client state, denormalized fields, and generated output as references or projections unless they are explicitly authoritative.

When two surfaces appear to own the same truth, resolve authority before adding synchronization logic.

## Respect Provenance and Trust

Classify values crossing a boundary as one of:

- authority fact
- stable reference
- command or proposal
- user-authored value
- derived projection

Pass the smallest value that preserves the contract. A reference or command is often safer than copied detail because the receiver can resolve current authority.

Users are authoritative for their own input, expression, preference, or intent. They are not authoritative for server- or business-owned facts such as permissions, price, inventory, eligibility, or existing entity state.

## Name Durable Semantics Directly

Durable models, cross-boundary fields, commands, events, and business operations should use direct, searchable names. Use the same name for the same semantic unless an explicit boundary translation exists.

If naming is difficult, test whether two concepts or authority states have been collapsed prematurely.

## Shape Data and Boundaries First

Before adding clever flow, retries, fallback heuristics, orchestration, or generalized machinery, inspect the data shape, ownership path, state representation, and boundary contract.

Prefer shapes that make valid behavior obvious and invalid behavior hard to express. Solve ambiguity with an explicit invariant or authority boundary rather than layers of guesses.

## Spend Complexity for Return

Each abstraction, layer, state holder, protocol, switch, dependency, and indirection must earn its cost through behavior, reliability, clarity, maintainability, or evolvability.

Measure before optimizing. Prefer simple algorithms and data structures until evidence shows a material bottleneck or correctness need. Consider marginal return: the next unit of complexity should still pay for itself.

Use patterns and object models when they clarify ownership or stable variation, not because a pattern name is available. Avoid premature generalization from one implementation.

## Project the Design into Code

APIs, DTOs, props, commands, events, state, control flow, tests, assertions, and observability should expose the chosen authority and boundary model. Tests should protect the contract rather than mirror incidental implementation.

When implementation friction repeatedly contradicts the design, return to evidence and revise the model or proof shape; do not bury the mismatch in adapters or exceptions.

## Review Questions

- Where is the authority, and are all other copies clearly projections?
- What provenance and trust cross each boundary?
- Does the data shape make the intended behavior simpler?
- Do names expose the durable semantic?
- What measurable return pays for each added complexity?
- Which test, assertion, or observation proves the contract?
