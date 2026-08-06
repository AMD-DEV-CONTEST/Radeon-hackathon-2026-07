# Working Protocol

This is the consumer's single operational contract. Root `AGENTS.md` references it without restating it.

## Interpret the Request

Use composable lenses, not fixed document routes:

- **Intent**: a product promise, behavior, scope, or policy may change.
- **Constraint**: a technical, dependency, environment, legal, or operational boundary changed while some higher-level intent may remain stable.
- **Reality**: observed behavior differs from expectation; gather evidence before proposing a cause or mutation.
- **Artifact**: the requested result is a bounded deliverable whose reuse is not yet established.

Lenses may combine; none selects the durable owner.

## Resolve the Owner

Choose ownership from the claim's meaning, provenance, and diagnosed cause:

1. Identify the changing truth and its consumer.
2. Prefer code, configuration, schemas, tests, assertions, or automation when they can enforce it.
3. Use product truth when the product promise changes.
4. Use a technical or operational document only for an expensive contract that implementation surfaces cannot preserve clearly enough.
5. Keep evidence in the task packet; a diagnosed cause determines any durable destination.

Do not hide unresolved ownership behind a posture or new document.

## Choose the Working Posture

- **Explore** maps unknowns, evidence, alternatives, and assumptions.
- **Solidify** turns supported findings into explicit claims, boundaries, or decisions.
- **Execute** applies an approved, sufficiently bounded state change.
- **Diagnose** explains a mismatch through reproducible evidence.

Postures may combine or recur; they change the work, never ownership.

## Keep a Task Control Surface

For non-trivial work, keep a human-readable packet under `tasks/` with exactly this minimum control surface:

- **Objective**: the outcome being pursued.
- **Guardrails**: boundaries and invariants that must remain true.
- **Verification**: objective proof of completion.
- **Current Truth**: evidence-backed understanding, decisions, and material uncertainty.
- **Next Step**: the next concrete action or blocking decision.

Split supporting material only when the control surface becomes hard to scan.

Tasks are disposable workspaces, not durable truth owners. Deletion follows the project root's retention rule directly and never requires a promotion review. When verified work changes durable truth, update its canonical owner during the work rather than rescanning tasks at deletion.

## Load and Search Progressively

Read the root instructions, this protocol, and the one governing owner first. Load implementation taste, local instructions, optional layers, or broader evidence only when their trigger is present.

Exclude tasks, generated output, dependencies, virtual environments, and caches from ordinary source and durable-doc search. Include them only when they are the target or hold required evidence.

## Mutation Gate

Permission to audit, discuss, or plan does not authorize durable mutation. Approval is scope-specific.

Before a non-local or cross-owner mutation, state the Impact Handshake:

- **Address and Object**: exact files, anchors, or symbols that will change.
- **State Diff**: objective `From -> To`.
- **Blast Radius**: downstream consumers and surfaces that may move.
- **Invariants**: behavior and authority that must remain unchanged.
- **Verification**: concrete proof that bounds side effects.

Pause for human confirmation when the change conflicts with an existing claim, the owner or evidence is unresolved, the blast radius crosses unclear owners, or a shortcut weakens an explicit guardrail. If new evidence changes the approved state diff or scope, return to discussion before applying it.

## Execute and Verify

Change the canonical owner first, keep derived surfaces synchronized in the same slice, and run verification proportional to risk. Report failures and remaining debt without silently expanding scope. Commit, publish, release, or perform external side effects only with the authority required by the project.

## Documentation Quality

- Keep one canonical statement per durable claim; remove duplication before compressing.
- Keep documents clean, concise, direct, and current.
- Optimize tokens without removing the owner, trigger, scope, invariant, exception, or verification needed to prevent ambiguity.
- Retain only content that improves routing, decisions, safety, or expensive-to-recover understanding.
