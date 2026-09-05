# Quality Control Revision Proposal

## Metadata

- Proposal ID: EXP-ASSET-P0-QA
- Parent iteration: EXP-ASSET-P0
- Classification: Requirement gap / necessary current-P0 scope change
- Created: 2026-07-23 AEST
- Requirement status: APPROVED
- Approved by: User
- Approval evidence: User replied “可以的。批准。” on 2026-07-24 AEST and
  added that component-specific performance directions must remain reasonably
  adjustable through a controlled process.
- Engineering status: NOT_STARTED
- Verification status: NOT_RUN
- Owner intent: The user will lead business-quality control across L1 product
  experience and L2 system capability, while the team retains implementation
  ownership.
- Evaluation confidentiality: Teammates receive the behavioral quality contract
  and optimization direction, but not the quality owner's hidden test code,
  private fixtures, gold labels, exact weights, pass thresholds, or scoring
  aggregation.

This approved supplement is incorporated into the parent requirement contract.
It fixes the business and safety gates while deliberately allowing versioned,
evidence-backed component-level metric and optimization adjustments.

## 1. Problem

The current P0 defines product behavior and benchmark evidence, but it does not
yet define how the quality owner will prevent implementation drift at each
milestone, how every change proves continued alignment, or how performance
optimizations are assigned to different business stages without degrading the
stages that require stronger reasoning, evidence fidelity, or privacy safety.

A single global “accuracy” or “tokens per second” number would hide the actual
trade-offs. For example, a faster Stage 4 is not valuable if applicability
boundaries become weaker, while a slower deterministic HTML renderer is also not
acceptable when no additional reasoning quality is gained.

## 2. Desired Outcome

Every L1 milestone and every critical L2 capability has a named quality gate,
developer-visible behavior contract, performance preference, and evidence
package. The quality owner maintains a separate blind-evaluation suite so the
implementation is optimized for the product contract rather than a disclosed
answer key. A change cannot advance when hidden or public evidence reveals a
blocking business, evidence, privacy, persistence, permission, or local-run
defect.

Performance experiments use a declared stage profile and frozen conditions.
They are promoted only when the intended latency, throughput, concurrency, or
resource metric improves beyond measurement noise without violating the stage's
quality floor.

## 3. Confirmed Direction

The user has already established the following direction:

- quality control covers both L1 product experience and L2 system capability;
- important milestones and their user-visible artifacts are formal review gates;
- business-quality checks and performance benchmarks are separate but linked;
- different stages may use different models, budgets, or optimization priorities;
- high-reasoning or high-safety stages must retain accuracy and evidence quality;
- low-risk, deterministic, or user-wait-sensitive stages should prioritize speed;
- no test code is required in this proposal; direction, stage goals, acceptance,
  and optimization policy must be settled first.
- teammates and their coding Agents must not receive private test code, hidden
  fixtures, exact scoring weights/cutoffs, or the full gold answer set.

## 4. Proposed Quality Model

Quality uses five independent dimensions rather than one global score:

1. **Fidelity** — Does the artifact preserve what the user/source actually said?
2. **Completeness** — Did the stage recover the required structure or mark gaps?
3. **Evidence and boundaries** — Are claims traceable, qualified, and limited?
4. **Control and safety** — Can the user correct, pause, approve, or block actions?
5. **Operational reliability** — Can state resume, errors terminate clearly, and
   the local path be reproduced?

A private numeric rubric never cancels a critical defect. Fabricated facts, privacy-gate
bypass, lost confirmed state, unauthorized execution, non-local core inference,
or an unreported terminal failure are hard failures regardless of average score.

## 5. Proposed Gate Policy

| Severity | Examples | Proposed result |
|---|---|---|
| Critical | Fabricated material fact; privacy/publication bypass; lost/corrupted confirmed state; unauthorized tool execution; core inference leaves the local path | Hard block and rollback |
| High | Wrong critical event/decision; failed correction or resume; inconsistent canonical/export facts; route policy materially wrong | Block milestone promotion |
| Medium | Non-critical wording, discoverability, secondary-route quality, or measurable but non-blocking performance regression | Conditional pass only with owner, issue and deadline |
| Low | Cosmetic or documentation polish with no behavioral effect | May pass with backlog entry |

## 6. Proposed Stage Profiles

| Stage | Quality objective | Performance preference | Optimization direction |
|---|---|---|---|
| M1 Boundary and goal | Correct source boundary, goal, provenance and first useful structure | **Fast with fidelity floor** | Short prompt/schema, streaming, minimal context, caching; no invented event to save a question |
| M2 Timeline and critical moments | High recall of explicit events, order, conflicts, cues and turning points | **Balanced / recall-biased** | Structured extraction, chunking for long input, parallel independent extraction, cached source parsing |
| M3 Decisions, actions, results and evidence | Precise links between cues, alternatives, decisions, actions, results and statement status | **Evidence-precision biased** | Stronger reasoning budget/model profile, schema validation, targeted retry; latency is secondary |
| M4 Lessons, counterfactuals and boundaries | Useful but supported lessons with limitations, counterexamples and transfer conditions | **Reasoning-quality biased** | Strongest approved reasoning profile, compact canonical context, evidence-linked self-check; avoid speed-first model downgrade |
| M5 Route readiness, privacy and approval | Correct eligibility, privacy findings, permission gates and content consistency | **Policy/safety biased** | Deterministic policy first, model-assisted detection second, human approval; parallelize only independent render work |
| Rendering and progress UI | Exact canonical-version consistency and truthful state | **Deterministic / speed biased** | Templates, caching, incremental update, parallel format rendering; no LLM where deterministic code is sufficient |

The profiles are current logical defaults, not final model names or permanently
fixed component strategies. Engineering may use
multiple local models or one model with different context, generation, and
validation budgets, provided the observed quality and performance meet the same
profile.

If a component has a better business-aligned metric or optimization direction,
the team may submit a versioned adjustment before evaluating the candidate. The
proposal must state the affected component and stage, baseline evidence,
business reason, quality floors, side effects and rollback. Quality-owner
approval applies the new definition prospectively; historical failures cannot
be relabelled, and private blind-test results cannot be used to tailor the rule.

## 7. Proposed Acceptance Criteria

| ID | Proposed criterion | Intended verification |
|---|---|---|
| QA-01 | Every work item and pull request identifies the affected parent AC IDs, L1 milestone, L2 capability, fixtures and expected evidence before review. | PR-template/review audit |
| QA-02 | Each milestone has developer-visible schema/invariant checks plus quality-owner-only hidden fixtures, gold annotations and a human business-review rubric. | Public/private test-inventory review by quality owner |
| QA-03 | Critical and high defects follow the proposed blocking policy; conditional passes identify an owner, residual risk and resolution date. | Gate-decision audit |
| QA-04 | Public fixture categories cover complete, incomplete, contradictory, privacy-risk, route-ineligible, correction and resume behavior; undisclosed variants test generalization at the same gates. | Private fixture-to-gate traceability matrix |
| QA-05 | A performance candidate declares its stage profile, primary metric and quality floors before measurement and uses the same frozen manifest as its baseline. | Experiment-plan review |
| QA-06 | No performance candidate is promoted when it introduces a critical defect, reduces required route/privacy correctness, creates an unsupported material fact, loses confirmed state, or hides a terminal failure. | Before/after regression report |
| QA-07 | Interactive, background-concurrent and stress scenarios are measured separately; overload queues or terminates visibly instead of silently dropping work or weakening the model without disclosure. | Load and degradation report |
| QA-08 | Every milestone review receives a compact team-facing evidence pack: affected requirements, public fixture results, artifact snapshots, performance delta, failure categories and unresolved risks. Exact private cases, weights and aggregate scoring remain quality-owner-only. | Quality-owner sign-off and disclosure review |

## 8. Public Contract and Blind Evaluation Separation

The repository contains the **team-facing quality contract**:

- product goals and non-negotiable behavioral invariants;
- named milestones and expected artifact responsibilities;
- performance preference for each stage;
- metric definitions and reproducible contest benchmark conditions;
- required evidence format, failure categories and rollback responsibility.

The quality owner keeps the **private evaluation system outside the shared
repository and outside teammate Agent context**:

- exact test code and test prompts;
- undisclosed fixture variants and adversarial cases;
- gold annotations and expected outputs;
- scoring dimensions' exact weights, pass cutoffs and aggregation;
- random seeds, perturbation templates and case-selection logic;
- the full failure-to-score mapping.

The team receives `PASS`, `CONDITIONAL`, or `FAIL`, the affected public
requirement, the failure class, severity, and only the minimum reproduction
information needed to correct the behavior. The quality owner should rotate or
retain undisclosed variants instead of revealing the complete hidden suite.

This does not make the final competition benchmark secret. Claims shown to the
judges—TTFT, throughput, VRAM, completion rate, local-run evidence and the
baseline/optimized comparison—must remain reproducible and disclose their
conditions. Hidden evaluation protects internal business-quality validation;
public benchmark evidence supports contest credibility.

Private QA material should live outside the Git checkout, preferably on the
quality owner's local machine. If a private suite must call the Radeon pod, the
runner should stay local and send requests over the private SSH path; payload
logging should be minimized and temporary remote artifacts removed after the
run. Because the shared pod uses one Unix account, it is not a strong secrecy
boundary.

## 9. Proposed Performance Promotion Rule

Before a candidate run, declare one primary objective such as TTFT, time to first
artifact, end-to-end latency, output throughput, peak VRAM, concurrency capacity,
or model-call count. All other business and quality metrics act as guardrails.

The team-facing rule is intentionally qualitative:

- the primary metric must improve materially beyond measured noise;
- there is no Critical or High regression;
- the declared business-quality floors remain satisfied;
- non-target latency, VRAM, completion and quality regressions stay within the
  quality owner's approved trade-off envelope;
- all failures, sample sizes and configuration changes remain visible.

Exact improvement thresholds, quality weights, pass cutoffs and aggregation are
part of the private evaluator. They should be set by the quality owner after the
first W7900 baseline and must not be copied into team prompts, PR templates or
shared repository files.

## 10. Proposed Concurrency Scope

The product is single-user P0, so concurrency must serve the business rather
than become an isolated server benchmark:

1. **Interactive primary:** one active refinement session; optimize TTFT,
   time-to-first-artifact and stage latency.
2. **Background secondary:** two concurrent tasks, such as refinement plus
   export/evaluation; preserve interactivity and state correctness.
3. **Stress evidence:** four and eight concurrent model requests/tasks to expose
   queueing, VRAM, throughput and failure behavior; this is diagnostic, not a
   promise that P0 supports eight simultaneous users.

When capacity is exhausted, quality-critical M3–M5 work should queue with a
visible state instead of silently routing to a weaker profile. Deterministic
rendering and independent eligible-route generation may run concurrently when
state/version consistency is preserved.

## 11. Proposed Review Rhythm

- **Every PR:** automated invariants, affected fixtures, requirement mapping,
  credential/privacy scan and regression summary.
- **Every milestone freeze:** quality owner reviews the public artifact evidence
  and separately runs the private blind-evaluation matrix.
- **Every performance experiment:** baseline/candidate manifest and guardrail
  report before promotion.
- **Before submission:** full AC/QA traceability, W7900 local evidence,
  baseline/optimized report and recorded end-to-end judge scenario.

## 12. Scope and Non-goals

### In scope

- L1 and L2 gate definitions;
- fixture/gold/rubric/evidence requirements;
- performance profiles and promotion/rollback governance;
- interactive/background/stress workload definitions;
- quality-owner review and sign-off format.
- public-contract/private-evaluator separation and disclosure boundaries.

### Out of scope

- test-runner implementation;
- exact model routing or model names;
- final numeric latency/throughput targets before baseline;
- production-scale multi-user SLOs;
- replacing human review with a model-as-judge score;
- training or fine-tuning.
- publishing hidden tests, exact gold answers, scoring weights or pass cutoffs.

## 13. Risks

- Too many manual gates can turn the quality owner into a bottleneck; automate
  invariants and reserve manual review for business meaning and material change.
- Gold fixtures can overfit one chair story; later authorized fixtures from
  study and software-project experiences should broaden coverage without
  changing the P0 contract.
- A model-as-judge can share the same blind spots as the generator; it may assist
  triage but cannot be the only evidence for factuality, privacy or usefulness.
- Arbitrary performance thresholds can reward noise; baseline variance and raw
  records must remain visible.
- Stage-specific routing can become architecture complexity; logical profiles
  should be validated before multiple models are introduced.
- Revealing the hidden suite through overly detailed failure reports can cause
  Agent overfitting; disclose the requirement and minimal reproduction, then
  retain or rotate other variants.
- Completely opaque feedback can frustrate developers; the public contract must
  remain clear enough to build the right product even though scoring internals
  stay private.

## 14. Approved Governance Defaults

The user approved these defaults on 2026-07-24 AEST:

1. Critical and High defects block; Medium may conditionally pass with an owner
   and deadline; Low may enter Backlog.
2. Optimize one interactive session first, validate two concurrent background
   tasks second, and use four/eight concurrency only as stress evidence.
3. Share metric definitions and stage preferences, but keep exact promotion
   thresholds, quality weights, hidden cases and aggregate scoring private; set
   them after the first baseline.
4. Run automated checks on every PR; the quality owner manually reviews the
   public evidence and separately runs the private blind suite at milestone
   freeze rather than every commit.

These defaults may be refined prospectively through the controlled-evolution
process when component evidence justifies it. The Critical/High business and
safety gates cannot be waived by a performance-only change.
