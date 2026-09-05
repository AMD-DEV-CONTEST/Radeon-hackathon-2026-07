# Coding-Agent Alignment Protocol

Use this protocol before a teammate's Codex, Claude Code, Cursor or other
coding Agent proposes or performs work in this repository.

## 1. Load context

Read the mandatory sources in [`README.md`](README.md), plus the task-specific
sources listed there. Inspect the current branch and working tree. Do not treat
chat summaries, old reports or generated plans as more authoritative than the
linked contracts.

## 2. Return an alignment report

Before architecture, estimates, task breakdown or code, return exactly these
six headings:

1. **Product objective** — one observable user outcome.
2. **P0 flow** — input, M1-M4 current-experience refinement, Knowledge Card
   readiness, summary-only relation discovery, user-confirmed detailed
   cross-asset RAG, M5 route evaluation, canonical save, preview, privacy
   approval and export in order.
3. **Evidence and permission boundaries** — facts versus inference, tool
   permission, privacy, local inference, public exposure and Git limits.
4. **In scope / out of scope** — current task versus P0 exclusions and Backlog.
5. **Acceptance and contest mapping** — affected `AC-*`, L1 milestone, L2
   capability gate, Track 2/submission relevance, public fixture, evidence
   checkpoint, expected packet files/storage tier, and expected public evidence.
6. **Questions or conflicts** — genuine blockers only; write `None` when
   aligned.

The report should be concise and specific to the assigned component. It must
not include implementation or pretend an unapproved assumption is decided.

## 3. Proposal contract

After alignment, a proposal must state:

- engineering route and why it fits;
- affected files/components and architecture boundaries;
- affected `AC-*`, L1 milestone and L2 capability gate;
- Track 2 value/local-inference/submission impact, or a reason it is not
  applicable to this bounded work package;
- behavior change and explicit non-goals;
- public tests/fixtures and evidence to be produced;
- evidence packet path, reproducible commands, failure record and storage tier
  required by [`EVIDENCE_RETENTION.md`](EVIDENCE_RETENTION.md);
- security, privacy, persistence, failure and rollback considerations;
- any material decision that still needs approval.

Implementation begins only when the proposal is approved. A change in product
outcome, audience, P0 scope, permissions or durable architecture returns to
Discover instead of being hidden inside an engineering choice.

## 4. Quality and optimization rules

- Preserve factual fidelity, evidence status, confirmed state, privacy,
  approval gates and local inference before optimizing speed.
- Publicly prove that cross-asset retrieval cannot run before Knowledge Card
  readiness and that detailed historical retrieval cannot run before explicit
  relation confirmation. Current-source grounding is a separate operation.
- Identify the target stage/component and its business preference before a
  performance experiment.
- Compare a Candidate with its baseline using a frozen manifest and preserve
  failed runs.
- Preserve product-version and engineering-evidence snapshots at the named
  checkpoints; do not reconstruct them only for the final demo.
- A component-specific metric or optimization direction may evolve through a
  prospective, versioned proposal using
  [`CHANGE_PROPOSAL_TEMPLATE.md`](CHANGE_PROPOSAL_TEMPLATE.md).
- Never alter goals after seeing a private blind-test result, and never ask the
  quality owner for the hidden answer key.

## 5. Stop and escalate when

- two authority files materially conflict;
- the task would change an approved acceptance criterion or P0 boundary;
- required private data, credentials, publication, permission expansion,
  destructive action or production/release authority is missing;
- a performance gain would require weakening a Critical/High quality gate;
- the requested work cannot be verified in the available environment.

State the exact blocker and the smallest user decision needed. Otherwise keep
working within the approved scope and preserve evidence.
