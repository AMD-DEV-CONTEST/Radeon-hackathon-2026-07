# Proportional Development Standard

Status: mandatory, team-visible

This standard decides **how much process a change needs**. It does not copy the
product, architecture, quality, evidence, competition, or Git contracts. Those
remain authoritative through [`spec/README.md`](README.md).

The goal is proportional control: protect product direction, privacy,
reproducibility, and Track 2 evidence without turning low-risk maintenance into
a milestone ceremony.

## 1. Choose the route before editing

### Lightweight route

Use this route only when the change is bounded, reversible, and does not alter:

- user-visible behavior or an accepted outcome;
- API, schema, persisted data, fixtures, or compatibility;
- dependencies, architecture, Agent/RAG flow, permissions, or privacy;
- model serving, ROCm/GPU behavior, benchmark conditions, or evidence claims;
- milestone promotion, competition claims, demo, or submission material.

Examples include a typo, a resolved-link repair, a comment correction, or a
test-only fix that does not weaken the tested contract.

The lightweight route requires:

1. state the intended outcome and non-goals;
2. use a task branch and keep the diff narrow;
3. run targeted tests plus the required repository checks;
4. record anything unverified and the simple rollback;
5. inspect the diff for secrets, private data, and unrelated changes.

It does **not** require a new Issue, the full milestone lifecycle, a complete
evidence packet, a W7900 run, or synchronous quality-owner review unless the
affected authority explicitly requires one.

### Material route

Use this route for features or changes to architecture, dependencies,
contracts, schema, state, permissions, privacy, RAG, model serving, GPU
behavior, benchmarks, milestones, demo, or submission claims.

Before implementation, freeze only the affected items:

- intended outcome and acceptance criteria;
- relevant contract/schema and public fixtures;
- accountable owner, dependency, and merge boundary;
- required verification and evidence tier;
- unresolved material decisions.

Then follow the existing milestone and review sources routed by
[`spec/README.md`](README.md). Do not invent a parallel lifecycle here.

### Escalation rule

Escalate a lightweight change to the material route when the diff or tests show
that one of the material boundaries is affected. Escalation must cite the
behavioral, safety, compatibility, or competition risk. Formatting preference
alone is not a reason to escalate.

## 2. Review by impact

Classify findings using the public quality contract:

- `BLOCKER`: material correctness, privacy, permission, reproducibility,
  compatibility, data-loss, or competition-compliance failure;
- `CONDITIONAL`: meaningful risk that can be accepted temporarily only with a
  named owner, bounded follow-up, and no false claim of completion;
- `NIT`: wording, style, organization, or other non-behavioral improvement.

Only blockers stop merge by default. A reviewer should directly repair safe,
mechanical documentation or formatting issues when practical rather than send
the author through a low-value revision loop. Green CI is necessary evidence,
not proof that the user journey or milestone is accepted.

## 3. Preserve evidence in proportion to the claim

| Change or claim | Minimum evidence |
|---|---|
| Documentation-only | resolved links, required repository checks, diff review |
| Test-only | demonstrated failure before/fix after when practical; proof the public contract was not weakened |
| Application behavior | targeted tests and observable output for the affected path |
| API/schema/persistence | contract tests, compatibility/migration reasoning, rollback |
| UI journey | reproducible interaction evidence for the affected state, including error/recovery when relevant |
| Agent/RAG/permission | trace or artifact showing grounding, proposal-versus-execution boundary, and deterministic policy result |
| W7900/ROCm or performance | sanitized exact-commit packet under `spec/EVIDENCE_RETENTION.md` and frozen benchmark conditions |

Do not fabricate a full evidence packet for a small patch. Do not use a small
patch label to avoid evidence required by the claim. Hidden QA materials and
private scoring remain outside Git.

## 4. Baseline and Candidate optimization

An accepted performance Baseline is immutable. Optimization may proceed with a
prospectively declared, versioned Candidate that records:

- the exact code, model, quantization, runtime, hardware, context, and task set;
- the single intended delta or a clearly bounded change set;
- frozen quality floors and comparability conditions;
- repeated measurements and raw sanitized outputs;
- an explicit rollback to the accepted Baseline.

A Candidate may refine implementation or workflow, not only repair
correctness, if it preserves the product contract and quality floors. It must
not rewrite the Baseline, cherry-pick favorable runs, or mix incomparable
conditions. Promotion occurs only through the existing E8 evidence and review
route.

## 5. Team flow and checkpoints

- Use the ownership and E2-E8 sequence in
  `docs/kinnyu/E2_E8_PIPELINE_EXECUTION_PLAN.md`.
- A checkpoint exists at a milestone or material contract boundary, not at
  every commit or maintenance patch.
- E2/E4/E6/E7 remain the combined deep-audit gates; E3/E5 remain lightweight
  asynchronous technical gates.
- Adjacent-stage preparation may continue within the approved boundary, so the
  quality owner is not a synchronous blocker before every change.
- Merge readiness requires substantive review, required checks, a clean scope,
  and an honest statement of what was not verified.

## 6. Ready, merge, and rollback

A change is ready when:

- its routed acceptance criteria are demonstrated;
- relevant checks pass, or a genuine blocker is recorded;
- no secret, private fixture, generated model, or unrelated user change is in
  the diff;
- documentation matches actual commands, paths, and behavior;
- rollback is clear and `/workspace` persistence assumptions remain valid.

Merge does not promote a product milestone unless the applicable milestone
gate explicitly says so. Reverting the merge commit is the default rollback
for a documentation-only change; behavior and data changes must document any
additional recovery steps before merge.
