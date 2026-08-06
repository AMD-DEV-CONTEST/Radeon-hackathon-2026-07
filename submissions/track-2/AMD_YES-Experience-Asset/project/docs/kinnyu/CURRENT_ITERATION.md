# CURRENT ITERATION

> **Owner-approved final-sprint amendment — 2026-08-05:**
> [`spec/FINAL_SPRINT_EXECUTION_PACKAGE.md`](../../spec/FINAL_SPRINT_EXECUTION_PACKAGE.md)
> governs remaining E5–E9 ownership, sequencing, evaluation disclosure, and
> review cadence. It supersedes older stage-by-stage approval, private blind
> testing, quality-owner promotion, and ownership instructions. Repository
> review found no implemented private suite/fixture/Gold Answer/secret score;
> all known evaluation intent is public in that package. Product acceptance
> behavior, safety/privacy/permission, phased RAG, local W7900/ROCm inference,
> evidence retention, and competition requirements in this contract remain.

## Metadata

- Iteration ID: EXP-ASSET-P0
- Title: Experience Asset P0 — From Raw Experience to Routed Deliverables
- Created: 2026-07-23 AEST
- Updated: 2026-08-03 AEST
- Requirement status: APPROVED
- Engineering status: E1_ACCEPTED / E2_E3_COMPETITION_EVIDENCE_PASS /
  E4_IMPLEMENTED_EVIDENCE_PACKET_PENDING
- Active engineering: current evidence baseline is exact clean
  `main@60503eb`. PR #16 (E2/M1), PR #20 (E3/M2), PR #22 (E4/M3), PR #23
  (GraphRAG MVP specification), and PR #26 (E6/E7 scope reduction) are merged.
  This record verifies only the E2/E3 competition-evidence boundary; it does
  not promote E4+, replace final product acceptance, or establish E8 performance.
- Promotion status: E1-A1/A2/A3, E1-B and the combined E1 gate are accepted;
  T06 is `PASS`
- Accepted E1 evidence:
  `evidence/milestones/e1-combined/20260727T055758Z/`; the earlier failed and
  local-correction packets remain append-only
- Execution plan:
  [`E2_E8_PIPELINE_EXECUTION_PLAN.md`](E2_E8_PIPELINE_EXECUTION_PLAN.md)
  is accepted and merged. It uses one accountable owner per E2–E7 milestone,
  bounded N+1 preparation, sequential merging and parallel E8 evidence lanes.
  E2/E4/E6/E7 are combined deep-audit gates; E3/E5 are lightweight
  asynchronous technical gates. Bounded Issue #15 freezes the three E2/M1
  checkpoints and is active on `codex/e2-m1-experience-brief`.
- E2 checkpoint status: the Contract / Schema + Fixture checkpoint remains
  frozen in [`E2_M1_CONTRACT_CHECKPOINT.md`](E2_M1_CONTRACT_CHECKPOINT.md).
  The exact-main W7900 Serving Reference S1 and real M1 Agent vertical slice
  now have a sanitized, independently reviewed `PASS` packet under
  `evidence/milestones/e2-m1-w7900/20260801T094735Z/`.
- Verification status: E1_PASS / E2_COMPETITION_EVIDENCE_PASS /
  E3_COMPETITION_EVIDENCE_PASS / E8_PERFORMANCE_NOT_VERIFIED
- Iteration status: OPEN
- Approved by: User
- Approval evidence: User replied “按照这些默认批准请求” and later explicitly
  requested the refinement-first UX and reproducible ROCm benchmark additions on
  2026-07-23 AEST. The user replied “可以的。批准。” on 2026-07-24 AEST to
  approve the quality-governance supplement, then required controlled flexibility
  for component-specific performance metrics and optimization directions. On
  2026-07-24 AEST the user replied “确认l3” and required all competition and
  project constraints to be readable by GitHub collaborators and their Agents.
  Later on 2026-07-24 AEST the user explicitly authorized resolving the
  independent risk-audit findings and required the Track 2 Agent architecture
  and capability combination to be made unambiguous before implementation. The
  user then explicitly required cross-asset RAG to occur only after the current
  Knowledge Card is reasonably complete, approved synchronizing the full
  requirement/L3/QA/GitHub surface, and authorized publishing this hardening
  branch. On 2026-07-27 the user reviewed the proposed E2–E8 ownership,
  dependencies and staggered pipeline, replied “没问题，单独创建一个pr”, and
  authorized this separate governance PR for quality-owner review. That
  approval did not authorize E2 implementation before the plan and Issue
  checkpoints were accepted. On 2026-07-28 the user required review to focus on
  functional/code risk rather than comments or PR formatting and requested
  fewer synchronous audits before E7. The approved governance amendment uses
  deep audits at E2/E4/E6/E7 and lightweight asynchronous gates at E3/E5.
  E2 has one asynchronous product review that does not block E3 unless it finds
  P0 drift; E7 is the only planned user hard-stop acceptance. On 2026-08-03
  AEST the user approved the two-layer performance selection: a frozen W7900
  service baseline and bounded profile screen with three finalists, followed by
  a complete-application baseline and business evaluation. The user selected
  concurrency 1 as primary, 2 as secondary and 4 as diagnostic stress, and
  permitted a fixed external judge only for public, synthetic or de-identified
  evaluation data with deterministic and human vetoes. Before implementation,
  the user requested a best-practice and deadline review. The resulting v1
  freezes eight same-model BF16 profiles, separates fixed-token performance
  from natural-output quality, and moves quantization to an optional three-hour
  compatibility probe so it cannot block the submission path.

## 1. Problem

People accumulate useful experience in conversations, notes, purchases,
projects, study sessions, and troubleshooting, but the reasoning and lessons
usually remain fragmented and hard to reuse. Existing notes or summaries do not
reliably separate events from interpretation, expose ambiguity during
refinement, preserve applicability boundaries, or turn one experience into
different audience-appropriate products.

The P0 must prove one complete path without becoming a generic note-taking or
publishing platform.

## 2. Desired Outcome

A user can submit a first-person experience and quickly receive a useful first
structure, then refine it with an Agent through five truthful, visible, editable,
and resumable checkpoints. The Agent prioritizes missing details that make the
experience reusable: context, critical moments, cues, alternatives, decisions,
actions, evidence, counterfactuals, and applicability boundaries. The result is
a persistent canonical Experience Asset. The system determines which of five
audience routes are appropriate, explains ineligible routes, renders an in-app
preview, and exports consistent HTML, Markdown, and JSON deliverables. Before
any external-audience shareable export, the user sees privacy and claim risks
and must explicitly approve the exact final version.

## 3. Users and Scenarios

- Primary user: An individual who has completed or is completing an experience and wants to preserve and reuse what was learned
- Main scenario: Convert an anonymized adaptation of a public office-chair trial, return, and replacement experience into a reusable Experience Asset and routed outputs
- Important edge scenarios:
  - incomplete or contradictory source material;
  - an experience that is not suitable for one or more audience routes;
  - sensitive personal, health, purchase, location, third-party, or screenshot data;
  - user correction after the Agent has made an incorrect inference;
  - a resumed asset that should retain version history and related-asset links.

## 4. Confirmed Decisions

- Stable value proposition: make tacit personal knowledge reusable.
- P0 implements the Experience Asset path; Idea Asset and Method Asset remain future extensions.
- Continuous means user-initiated capture plus persistent cross-session evolution, not automatic surveillance.
- One canonical Experience Asset is the source for every preview and export.
- The five delivery routes are private/self review, beginner, peer, potential customer/evaluator, and public.
- The P0 contract defines all five audience routes, but route eligibility is
  conditional per asset; implementation and evidence must not fabricate an
  unsuitable output or claim an unverified route capability.
- P0 uses one durable LangGraph orchestration Agent with specialized nodes,
  scoped local retrieval and deterministic Runtime policy; it does not use a
  free-form multi-Agent team.
- The judge-visible Agent combination is multi-step planning, phase-gated local
  RAG, structured tool calls, durable local multi-turn memory, and
  permission/privacy enforcement. Capabilities are claimed only after real
  implementation and W7900 evidence.
- Local retrieval has two intentionally different phases. M1-M4 may ground the
  current experience using its approved source spans and prior versions of the
  same asset. Cross-asset retrieval is forbidden until M4 produces a
  `KnowledgeCardReady` state. The first cross-asset pass returns summary-only
  candidates and relation reasons; detailed historical evidence is retrieved
  only for relations explicitly confirmed by the user.
- The office-chair fixture uses only paraphrased, anonymized facts derived from a public case and is labelled as an adapted test fixture.
- The fixture's research provenance is the public Reddit post `https://www.reddit.com/r/OfficeChairs/comments/hem1s7/`; the product must preserve the source URL without presenting the adapted narrative as first-party testimony.
- The final competition demonstration should replace the fixture with an explicitly authorized real experience where practical.
- The user sees intermediate outputs during refinement and can correct ambiguity or drift before final generation.
- Refinement is the P0 product center, not a hidden preprocessing step before export.
- Refinement has five stable milestones: source boundary and goal; timeline and critical moments; decisions/actions/results and evidence; lessons/counterfactuals/applicability; route readiness and privacy approval.
- Every milestone produces an autosaved, editable intermediate artifact. The first useful artifact is an `Experience Brief v0.1`, shown after initial ingestion rather than after the full interview.
- Clarification is progressive: normally one to three highest-value questions per round, with a short reason for each question and controls to answer, edit, skip, defer, pause, resume, or generate with the current evidence.
- Progress feedback reports actual completed milestones, confirmed facts, unresolved questions, route readiness, and saved version. It must not display fabricated advancement or an unsupported countdown.
- A determinate percentage is allowed only when it maps to known work units. An ETA is allowed only after comparable historical runs exist and must be presented as an evidence-based range with uncertainty.
- Any external-audience shareable export requires a risk review and explicit
  final user approval. A private/self download remains labelled as not approved
  for external sharing.
- P0 generates an interactive application preview plus real shareable/reprocessable files.
- P0 accepts conversation input, pasted text, and uploaded `.txt` and `.md` files.
- A destructive deletion uses a second confirmation and then immediately removes the product-managed asset and exports; the system explains that external copies cannot be recalled.
- Each routed generation lets the user choose Chinese or English; simultaneous bilingual generation is not required.
- P0 records a reproducible W7900/ROCm baseline and optimized comparison before setting a hard latency target. At minimum it captures time to first token, task latency, output throughput, peak VRAM, task completion, failures/recovery, and local-run evidence under a frozen manifest.
- E2 records an immutable early model-serving reference after E1 compatibility.
  The approved Stage 1 performance screen freezes that reference as `S0`,
  evaluates eight prospectively declared same-model BF16 serving profiles in
  separate controlled-performance and business-quality lanes, and advances at
  most three profiles that pass strict compatibility, quality, locality,
  stability and evidence gates. Quantization is an optional separately
  versioned compatibility probe, not a deadline-critical requirement. The
  first accepted complete Agent is frozen separately as
  `A0`; only the same full application and business fixtures may decide the
  final profile. No service-only result can promote a product default.
- Critical and High quality defects block milestone promotion; Medium defects may pass only conditionally with an owner, residual risk and deadline; Low defects enter Backlog.
- Automated public checks run on every PR. Private blind evaluation is bundled
  at E2/E4/E6/E7 deep-audit gates; E3/E5 use lightweight asynchronous technical
  gates unless concrete Critical/High evidence requires escalation.
- Team members receive business invariants, stage preferences, metric definitions and evidence requirements, but not private cases, gold outputs, exact weights, cutoffs or aggregation.
- Single interactive-session quality is the first workload priority, two
  concurrent requests are secondary, and four-request concurrency is diagnostic
  stress evidence rather than a ranking advantage.
- Stage and component performance preferences are controlled, versioned defaults rather than permanent implementation rules. Evidence-backed changes may be proposed before Candidate evaluation, but cannot waive business/safety gates or retroactively fit observed blind-test results.
- Product-version snapshots and engineering evidence are separate mandatory
  histories. Every PR retains traceable checks/risk/rollback context; deep-audit
  milestones, GPU gates, Baseline/Candidate and final submission freezes preserve
  full sanitized, reproducible packets while large/raw/private material remains
  in its approved storage tier.

## 5. Assumptions

- P0 is single-user and private by default.
- P0 is text-first; raw image, receipt, audio, and video understanding is deferred, while users may manually provide extracted text.
- Chinese and English are the two supported output choices; contest documentation can remain English.
- HTML is the share-ready artifact, Markdown is the editable artifact, and JSON is the canonical machine-readable artifact.
- An explicitly confirmed deletion removes an asset and its product-managed exports immediately; Git history and user-created external copies are outside that guarantee.
- Numeric latency targets will be set after measuring a local W7900 baseline; P0 records inference, Agent, and refinement-UX outcomes rather than selecting a single flattering speed number.

## 6. Open Questions

- No blocking product questions remain. The numeric latency optimization target will be proposed during engineering after a measured W7900 baseline.

## 7. Scope

### In scope

- User-created Experience Assets that can be resumed and versioned across sessions
- Visible, editable checkpoints for event boundary, timeline, decisions/actions/results, evidence, extracted lessons, applicability boundaries, and delivery preview
- A refinement workspace with five stable milestones and the intermediate artifacts `Experience Brief`, `Critical Moment Map`, `Decision and Evidence Ledger`, `Insight and Boundary Map`, and `Route Readiness Matrix`
- Progressive high-value elicitation covering situation and goal, timeline and critical incidents, cues and alternatives, decisions and actions, observed results, surprises, counterfactuals, reusable lessons, evidence strength, uncertainty, sensitive details, and applicability boundaries
- Truthful progress and persistence feedback, including current milestone, completed artifacts, confirmed/unresolved counts, route readiness, version, autosave state, and a clear pause/resume path
- A canonical asset containing source references, context, goal, constraints, alternatives, decisions/actions, results/evidence, lessons, boundaries, audience, maturity, versions, and confirmed relations
- Clear separation of source facts, user judgments, Agent inferences, and missing/uncertain information
- Simple confirmed relations such as supplement, counterexample, same theme, prerequisite, follow-up, and method reuse
- Scoped current-experience retrieval over approved source spans and prior
  versions of the same asset during M1-M4, returning provenance/evidence
  references and a visible no-match result
- A post-M4 cross-asset RAG gate: after the current Knowledge Card is confirmed
  or explicitly accepted complete-with-gaps, summary-only candidate discovery
  may run; detailed historical evidence remains blocked until the user confirms
  the relation, and retrieved content cannot silently rewrite the current asset
- Eligibility decisions for all five audience routes, including explanations for ineligible routes
- Route-specific preview and output generation without changing the underlying facts
- Consistent in-app preview, self-contained HTML, Markdown, and JSON outputs
- Pre-export privacy and claim-risk review with user-controlled keep, generalize, or remove decisions
- Office-chair public-case-derived test fixture plus incomplete, privacy-risk, correction, and ineligible-route evaluation variants
- Local open-model core inference on the Radeon Cloud W7900 through ROCm
- Traceability sufficient to inspect versions, route decisions, evidence use, privacy findings, and failures
- A frozen benchmark fixture suite, machine-readable run manifest, baseline/optimized profiles, raw run records, and a human-readable comparison report
- Separate model-serving, Agent end-to-end, and refinement-UX measurements so that one layer cannot conceal regressions in another
- Public L1 milestone and L2 capability gates, per-PR evidence packs, and quality-owner milestone sign-off
- A versioned, prospective process for component-specific benchmark or optimization-direction adjustments
- Append-only, storage-tiered engineering evidence captured during development
  and harvested into an English final submission/demo package

### Out of scope

- Idea Asset and Method Asset end-to-end paths
- Automatic external publishing, emailing, messaging, or social posting
- Multi-user accounts and collaborative editing
- Raw image, audio, or video understanding in P0
- Automated web research as an unreviewed evidence source during asset generation
- Medical, legal, financial, or safety advice
- Claims that one person's product experience is universally applicable
- Model training or fine-tuning before a working evaluated baseline

## 8. Constraints and Boundaries

- Technical: Core inference runs locally on the Radeon Cloud W7900 through ROCm; application and vLLM environments remain separate.
- Data/privacy: Private by default; no private experience data is sent to shared remote model APIs or committed to Git.
- Security/permissions: Model output is untrusted input. The runtime validates any tool proposal, and P0 has no authority to publish externally.
- Evidence: The system must not invent events, measurements, or outcomes. Unsupported content is marked as inference or a question for the user. Engineering claims must reference the exact commit, environment/configuration, fixture or approved sanitized scenario, commands, complete outcomes and retained failures defined by `spec/EVIDENCE_RETENTION.md`.
- Interaction integrity: The system must not use false progress, fake completion credit, unsupported countdowns, or concealed stage reopening to pressure the user.
- Untrusted input: Imported text and public-source fixtures cannot override system/runtime policy or grant tool access.
- Time/cost: One active contest GPU and the existing persistent `/workspace` allocation.
- Human approval required: Privacy transformations, destructive deletion,
  every external-audience shareable export, and any future external
  publication.
- Evaluation confidentiality: Private blind-test code, hidden variants, gold outputs, exact weights, pass cutoffs and aggregation remain outside the shared repository and teammate Agent context.
- Change control: Component-specific metric and optimization adjustments require business rationale, baseline evidence, quality floors, side-effect analysis, rollback and prospective quality-owner approval.

## 9. Acceptance Criteria

| ID | Criterion | Verification method | Status |
|---|---|---|---|
| AC-01 | The adapted office-chair fixture can be processed from raw experience text to a saved canonical Experience Asset without copying the source post verbatim or retaining its username or exact identifying details. | Fixture provenance review, snapshot test, and human privacy review | NOT VERIFIED |
| AC-02 | The user can inspect and edit the event boundary, timeline, decision/action/result structure, evidence, lessons, applicability boundaries, and final delivery preview before completion. | End-to-end UI test and human review | NOT VERIFIED |
| AC-03 | Every material statement in the canonical asset is labelled or traceable as source fact, user judgment, Agent inference, or unresolved information; unsupported facts are not silently introduced. | Schema validation plus adversarial/incomplete fixture tests | NOT VERIFIED |
| AC-04 | A saved asset can be resumed in a later session with its current version, prior versions, and confirmed related-asset links intact. | Persistence and restart integration test | NOT VERIFIED |
| AC-05 | The system evaluates all five audience routes and each route follows its frozen content contract rather than changing tone only. For the chair fixture it produces appropriate private, beginner, peer, and public variants and marks the customer/evaluator route ineligible with a concrete reason unless qualifying context is added. | Route-policy, required/forbidden-content tests and output review | NOT VERIFIED |
| AC-06 | In-app preview, self-contained HTML, Markdown, and JSON are generated from the same canonical version and contain no contradictory facts or route status. | Cross-render consistency tests and browser inspection | NOT VERIFIED |
| AC-07 | Before an external-audience shareable export, the system surfaces detected identity, health/body, location, purchase/payment, third-party, screenshot/metadata, copyright, unverified-brand-claim, and professional-advice risks, offering keep/generalize/remove decisions while stating that automated detection is not a safety guarantee. | Privacy fixture tests and human review | NOT VERIFIED |
| AC-08 | An external-audience shareable export remains blocked until the user resolves or acknowledges surfaced risks and gives explicit final approval; private/self downloads are marked as not externally approved, and no P0 flow posts externally. | Permission-state integration tests | NOT VERIFIED |
| AC-09 | User corrections update the canonical asset and regenerate affected previews/exports without silently reverting confirmed facts. | Correction and regeneration end-to-end test | NOT VERIFIED |
| AC-10 | Missing, conflicting, or insufficient material produces a visible question, warning, or ineligible state rather than a fabricated polished output. | Incomplete and contradictory fixture tests | NOT VERIFIED |
| AC-11 | The core Agent generation path runs through a local open model on the W7900/ROCm environment, and the run records model identity, configuration, timing, model-call count, and terminal success or failure. | Radeon Cloud integration test and trace inspection | NOT VERIFIED |
| AC-12 | After a second destructive confirmation, the user can immediately delete an asset and its product-managed exports, and the system reports what was deleted and any external/user-created copies it cannot delete. | Deletion integration test and audit review | NOT VERIFIED |
| AC-13 | The user can start or extend an asset through conversation, pasted text, or an uploaded `.txt` or `.md` file; unsupported file types fail with a clear explanation. | Input integration and error-state tests | NOT VERIFIED |
| AC-14 | Each eligible routed deliverable can be generated in either Chinese or English selected by the user, without requiring simultaneous bilingual generation. | Route/language matrix test and human output review | NOT VERIFIED |
| AC-15 | Initial ingestion produces an editable, autosaved `Experience Brief v0.1`; the five refinement milestones each expose their named intermediate artifact and can be paused, resumed, corrected, or revisited without losing confirmed information. | End-to-end milestone, autosave, resume, and correction tests | NOT VERIFIED |
| AC-16 | Normal refinement asks no more than three prioritized questions per round, explains why each requested detail matters, and supports answer, edit, skip, defer, pause, resume, and “generate with current evidence” without converting unanswered items into facts. | Conversation-policy tests and moderated usability review | NOT VERIFIED |
| AC-17 | Progress feedback is derived from actual milestones, confirmed statements, unresolved questions, route readiness, and saved version. Determinate percentages map to known work units; any ETA is an evidence-based range, and indeterminate work never receives a fabricated countdown. | State-to-UI invariant tests and human review | NOT VERIFIED |
| AC-18 | The Agent demonstrates the complete Track 2 loop: clarify goal/private material/permissions/acceptance criteria; load durable local state; create or revise a visible multi-step plan; retrieve source-linked local memory; use W7900/ROCm local inference to propose a structured tool call; enforce Runtime allow/deny and execute one bounded local effect; verify the actual result; then persist/deliver, ask for adjustment, or stop safely. | Recorded Radeon Cloud end-to-end scenario, restart and allow/deny trace review | NOT VERIFIED |
| AC-19 | Every performance run records a reproducibility manifest containing hardware, OS/container, driver/ROCm/PyTorch/vLLM versions, model source/revision, dtype/quantization, context and token limits, server arguments, fixture/workflow versions, warm-up, repetitions, concurrency, timestamps, and success/failure outcomes. | Manifest schema validation and benchmark artifact review | NOT VERIFIED |
| AC-20 | A baseline and each claimed optimization are compared on the same frozen tasks and measurement method using repeated runs. The Candidate prospectively declares its intended model/quantization/context/serving or workflow delta; every non-declared condition remains identical. Reports include sample size, failures, mean/median/p95 where applicable, TTFT, end-to-end latency, output tokens/s, peak VRAM, task completion rate, tool errors/recovery, and verifiable local-run evidence. | Benchmark plan/manifest comparison, runner tests, raw-record audit, and report review | NOT VERIFIED |
| AC-21 | Product evaluation records time to first useful artifact, clarification questions/rounds, milestone completion and abandonment/resumption, correction recovery, evidence coverage/unsupported-claim rate, route readiness, and a lightweight user rating of clarity, progress, control, and trust. | Instrumentation tests plus fixture and moderated-use report | NOT VERIFIED |
| AC-22 | Every work item and PR supplies enough outcome, risk, checks/evidence and rollback context for risk-based review; milestone/deep-audit work also identifies affected AC/L1/L2/fixtures. Template formatting alone is advisory when the information is otherwise clear. | PR review and advisory-metadata audit | NOT VERIFIED |
| AC-23 | Each refinement milestone has developer-visible schema/invariant checks. Private quality-owner evaluation is bundled at E2/E4/E6/E7, may be triggered earlier by concrete Critical/High evidence, and remains outside the shared repository together with variants, gold outputs and exact scoring. | Public/private inventory, cadence and disclosure audit by quality owner | NOT VERIFIED |
| AC-24 | Critical and High defects block promotion; a Medium conditional pass records owner, residual risk and deadline; Low issues are recorded in Backlog. | Gate-decision audit | NOT VERIFIED |
| AC-25 | Public fixture categories cover complete, incomplete, contradictory, privacy-risk, route-ineligible, correction and resume behavior; undisclosed variants evaluate the same public requirements without exposing their contents. | Public fixture inventory plus private gate-coverage sign-off | NOT VERIFIED |
| AC-26 | Before measurement, each performance Candidate declares its stage/component profile, primary metric, quality floors, frozen comparison manifest, side effects and rollback. | Experiment-plan and manifest review | NOT VERIFIED |
| AC-27 | No Candidate is promoted when it introduces a Critical/High regression, unsupported material fact, privacy/permission bypass, lost confirmed state, concealed terminal failure or non-local core inference. | Public regression report plus private quality-owner result | NOT VERIFIED |
| AC-28 | Interactive, background-concurrent and stress scenarios are measured separately; overload produces a visible queue or safe terminal state and never silently weakens a quality-critical stage. | Load, queue and degradation report | NOT VERIFIED |
| AC-29 | Metric or optimization-direction changes are versioned, justified by component and business evidence, approved prospectively and preserve historical results; they cannot be tailored after seeing private blind-test results. | Change-log, review-timestamp and benchmark-version audit | NOT VERIFIED |
| AC-30 | Cross-asset RAG cannot run before the current Knowledge Card reaches the post-M4 readiness gate. Candidate discovery reads only approved local summaries and returns relation reasons; detailed retrieval is limited to assets whose relation the user explicitly confirms. A no-match or declined relation is a normal visible outcome, and historical content never silently changes current facts. | Retrieval-phase trace checker, pre-gate/confirmation denial tests, no-match test, relation-scope test, and current-asset snapshot comparison | NOT VERIFIED |
| AC-31 | Stage 1 freezes `S0` and all service profiles, controlled fixed-token performance workloads, natural-output business-quality workloads, deterministic checks, sample counts, scoring code and hashes before measurements are scored. Every profile runs on the same W7900/ROCm/vLLM conditions, retains failures and rollback evidence, and passes locality, stability, 8K-capability, quality, unsupported-fact, VRAM-headroom and evidence gates before ranking. Performance and quality lanes cannot be silently aggregated as if their output lengths were equal. | `serving-screen-v1` contract/hash manifest, raw evidence packets, gate report and reproducible score table | NOT VERIFIED |
| AC-32 | No Stage 1 finalist becomes the product default until the complete Agent and `A0` are frozen and the finalist is evaluated on identical application code, prompts, runtime policy, data seed and business fixtures. Deterministic business/safety gates and human review can veto an external semantic judge or a faster numeric result. | A0-relative end-to-end report, judge provenance, disagreement review and signed final recommendation | NOT VERIFIED |

## 10. Refinement Interaction Contract

The refinement loop borrows from Critical Incident Technique and Cognitive Task
Analysis without pretending to conduct a formal psychological assessment. It
uses concrete events and critical decisions to recover the details that make
experience transferable.

| Milestone | Highest-value prompts | Required visible artifact | Completion evidence |
|---|---|---|---|
| 1. Source boundary and goal | What happened, for whom, under what constraints, and what should this asset help with? | `Experience Brief v0.1` | Event boundary, source provenance, user goal, and obvious sensitive areas are visible |
| 2. Timeline and critical moments | What changed, what was noticed, and where did the path turn? | `Critical Moment Map` | Ordered events and critical moments are confirmed or marked unresolved |
| 3. Decisions, actions, results, and evidence | What cues and alternatives existed, why was an action chosen, and what result was actually observed? | `Decision and Evidence Ledger` | Decisions link to actions/results; statements show fact, judgment, inference, or unresolved status |
| 4. Lessons, counterfactuals, and boundaries | What would change next time, when does the lesson apply, and when might it fail? | `Insight and Boundary Map` and `KnowledgeCardReady` decision | Lessons include support, limitations, counterexamples, and transfer conditions; the user confirms the card or explicitly accepts visible gaps before any cross-asset search |
| M4→M5 relation gate | Which prior experiences might be relevant, and does the user want to compare them? | Summary-only relation candidates, then confirmed links | No cross-asset search before readiness; no detailed historical read before confirmation; no-match/decline is visible and valid |
| 5. Route readiness and approval | Who can safely use this, what is missing, and what privacy/claim changes are required? | `Route Readiness Matrix` plus delivery preview | Each route is ready, blocked, or ineligible with a reason; only user-confirmed historical evidence may inform routing; every external-audience shareable export remains gated |

Interaction rules:

- show useful structure before asking for exhaustive detail;
- ask the fewest questions that materially improve evidence, decisions, or boundaries;
- explain the purpose of a question and allow the user to decline it;
- acknowledge concrete progress such as “two critical moments confirmed”, not
  generic praise, streaks, or pressure mechanics;
- display uncertainty and make correction efficient;
- autosave every confirmed checkpoint and make “continue later” a normal path;
- if new evidence reopens a completed milestone, preserve the prior state and
  show the reason instead of silently moving progress backwards.
- keep the M1-M4 interview independent of other Experience Assets; once the
  Knowledge Card is ready, show relation candidates without importing their
  details, and ask the user which relations to confirm before comparison.

## 11. Benchmark and ROCm Evidence Contract

The formal competition rules remain authoritative. The Track 2 presentation
adds a practical judging standard: claims such as “local” or “faster” need
verifiable data. P0 therefore treats the following as required evidence.

### Measurement layers

1. **Model serving** — time to first token, prefill/input throughput when
   available, output tokens per second, request latency, peak VRAM, server
   errors, and concurrency behavior.
2. **Agent task** — end-to-end task latency, model-call count, task completion,
   terminal state, tool-call success/error/recovery, retry count, evidence
   coverage, unsupported claims, and privacy/route correctness.
3. **Refinement product** — time to first useful artifact, question burden,
   checkpoint completion/resume, corrections, route readiness, and user-rated
   clarity/progress/control/trust.

### Comparison discipline

- freeze public, incomplete, contradictory, privacy-risk, route-ineligible,
  correction, and resume variants of the office-chair fixture;
- warm up before measured runs and retain every failure;
- compare baseline and Candidate with the same task and measurement method;
  declare the intended model/quantization/context/serving/workflow delta before
  measurement and keep every non-declared condition frozen;
- report raw run records plus sample size, mean, median, p95 where meaningful,
  and failure rate; never report only the best run;
- store model/server and end-to-end Agent results separately;
- preserve an environment/model/configuration manifest and a rollback profile.

### ROCm optimization ladder

1. Prove the local path with `amd-smi`, `rocminfo`, PyTorch HIP/device output,
   vLLM startup evidence, and a trace showing private model traffic stayed on
   the controlled pod.
2. Freeze the stable BF16 reference as `S0` before Stage 1 parameter,
   quantization or attention-backend Candidates, and later freeze the complete
   product as `A0` before any finalist can become the product default.
3. Tune evidence-backed parameters such as context budget, output caps,
   `gpu-memory-utilization`, `max-num-seqs`, batching/concurrency, warm-up,
   prefix caching, prompt size, and unnecessary model-call count.
4. Test quantization, attention backends, or vLLM optimization levels only when
   supported by the exact vLLM/ROCm/W7900 stack; record incompatibilities rather
   than blindly porting a CUDA/FA2 recipe.
5. Keep a known-good profile and accept an optimization only when the frozen
   benchmark shows a worthwhile speed/resource improvement without unacceptable
   completion, evidence, privacy, or UX regression.

The executable benchmark specification belongs in
`docs/team-alignment/BENCHMARK_PLAN.md`.

## 12. Requirement Risks

- A broad audience-router scope may produce superficial variants rather than materially different products.
- The public fixture may be mistaken for first-party testimony unless its adapted provenance is visible.
- Privacy review can create false confidence; the product must present findings as review assistance, not a guarantee.
- Long conversations can exceed context limits unless the canonical asset and checkpoints remain compact and versioned.
- Generated HTML may look publishable while containing unsupported conclusions; cross-render evidence checks are essential.
- A numeric latency goal chosen before baseline measurement could distort model selection or encourage unsafe shortcuts.
- A decorative progress bar or optimistic ETA could reduce trust when Agent work is non-deterministic; progress must be state-derived.
- Excessive questioning could turn experience capture into an interview burden; each prompt must earn its place through measurable information gain.
- Server-level token speed can improve while task completion, evidence quality, or perceived control regresses; the three benchmark layers must remain separate.
- Radeon compatibility varies by exact driver, ROCm, vLLM, model, quantization, and attention backend; every claimed optimization needs a frozen manifest and rollback.

## 13. Engineering Proposal

- Proposal: [`L3_ENGINEERING_PLAN.md`](L3_ENGINEERING_PLAN.md)
- Route: Correctness-first modular monolith delivered as thin vertical slices;
  the Agent application and vLLM remain separate processes/environments.
- Agent architecture: One durable LangGraph orchestration Agent with explicit
  plan/retrieve/propose/validate/execute/verify/persist nodes, scoped SQLite
  local retrieval and deterministic Runtime permission. See
  `docs/team-alignment/AGENT_ARCHITECTURE.md`.
- Route confidence: HIGH for a single-user hackathon P0; revised after
  quality-owner review and explicitly accepted by the owner.
- Reason: This minimizes distributed-state and deployment risk while preserving
  explicit domain, workflow, inference, persistence, policy, renderer,
  observability, API, and UI boundaries.
- Impacted areas: Product application scaffold, full domain schemas, immutable
  versions, SQLite persistence, local inference adapter, five milestone
  workflows, route/privacy/approval policy, deterministic preview/exports,
  deletion, UI, public QA integration, and three-layer baseline evidence.
- Proposed checkpoints: E0 engineering contract; parallel E1-A Agent-core/model
  viability and E1-B React foundation; one accountable owner per E2 M1,
  E3 M2, E4 M3, E5 M4, E6 M5, and E7 preview/export/deletion with bounded
  N+1 preparation but sequential promotion; an independently frozen Stage 1
  W7900 service screen; parallel E8 model and product/UX evidence followed by
  immutable `A0`; E9 English submission and demo freeze assembled from retained
  history.
- Test strategy: Unit and integration tests per module; existing seven public
  fixture categories; artifact and milestone gates from M1 onward; browser and
  restart tests; mandatory 14B/W7900 compatibility evidence at E1, first-slice
  serving reference at E2, Stage 1 `S0`/Candidate service evidence under AC-31,
  and complete Radeon Cloud E2E plus `A0`/Stage 2 evidence at E8; clean-checkout
  reproduction and submission/media evidence audit at E9; bundled quality-owner
  blind review at E2/E4/E6/E7 and lightweight asynchronous technical gates at
  E3/E5.
- Selected P0 material choices: FastAPI/Pydantic backend; LangGraph orchestration;
  SQLite product datastore; immutable full JSON version snapshots with a
  mutable current pointer; React/Vite UI; deterministic Jinja2 HTML plus
  Markdown/JSON serializers; localhost OpenAI-compatible vLLM adapter; initial
  Qwen2.5-14B-Instruct BF16/8K profile.
- Snapshot boundary: A version snapshot contains one complete validated
  canonical Experience Asset JSON, not duplicate attachments, exports, model
  weights, or raw traces. Schema-versioned repositories preserve a future
  normalization/event-storage migration path.
- Team execution: `kinnyuww` is the quality/integration gate; `Eas000n` owns
  Lane A Agent-core/API/persistence/local-inference work by default;
  `1olaqua616-web` owns Lane B React/interaction/rendering/browser evidence by
  default. Both developers may begin bounded E1 work after E0 merges; shared
  contracts freeze first and combined behavior passes one milestone gate.
- Deferred material choice: A numeric latency target remains unset until a
  measured reference/Baseline. The proposed model source/revision, file
  manifest and historically known-good vLLM wheel are now frozen inputs; they
  become an accepted E1 profile only after current-pod SHA/load/tool-call checks
  and a reviewed dependency lock. A later quantized Candidate remains
  conditional on exact W7900/ROCm/vLLM support and rollback evidence.
- Risks and rollback: The proposal defines last-valid-version recovery,
  dependency invalidation, version/hash-bound approvals, explicit run terminal
  states, known-good model rollback, and one bounded Issue/branch/PR per work
  package.
- Engineering approval: APPROVED
- Draft authorization evidence: On 2026-07-24 the user approved starting L3-0
  planning after reviewing the proposed Issue/PR and Baseline-first sequence.
- Revision authorization evidence: On 2026-07-24 the user explicitly selected
  React for the frontend, asked the primary Agent to complete and clarify the
  L3 proposal directly, and specified that the two collaborators begin through
  generated Issues only after L3 is accepted.
- Evidence-retention authorization evidence: On 2026-07-24 the user confirmed
  that uploading the evidence policy is necessary and required teammate Agents
  to preserve historical proof during implementation so it is directly
  available for the final demo and submission.
- Final L3 acceptance evidence: On 2026-07-24 the user replied “确认l3” and
  required competition and other project constraints to be included in the
  teammate-readable GitHub specification route.
- Risk-review authorization evidence: Later on 2026-07-24 the user directed the
  primary Agent to resolve the E1 sizing, environment freeze, early reference,
  Agent-capability, route-contract and submission-readiness findings, and
  selected a later quantized-model Candidate as the intended optimization
  experiment; optional-bonus eligibility remains unconfirmed.
- Engineering execution state: `E1 ACCEPTED / E2 ACTIVE`. PR #7,
  PR #8, PR #12 and PR #13 are accepted and merged at `main@b053f66`; the bounded
  correction at `2deaad7`, parser normalization at `de72a6c`, and
  exact-current W7900/ROCm/14B Runtime packet were accepted. T06 is `PASS`.
- E1-A checkpoint boundary: E1-A1 Contract, E1-A2 Durable fake loop, and E1-A3
  Real W7900 gate are three independently reviewable checkpoints inside the one
  E1-A Issue #5 / PR #7. They are not three separate Issues. All three
  checkpoints were accepted during PR #7 review.
- PR #8 re-vendored the accepted final E1-A contracts and was accepted/merged.
- Active E2 boundary: PR #13 is merged at `main@b053f66`; Issue #15 owns the M1
  Experience Brief slice. Its Contract / Schema + Fixture checkpoint is
  confirmed and its LangGraph vertical slice is in final integration. E2 remains
  unpromoted until its W7900 S1, Vertical Slice V1 evidence and independent
  quality decision are complete. E3 may perform only the bounded preparation
  allowed by the accepted pipeline until E2 promotion.

## 14. Execution Record

### 2026-07-28 risk-based review amendment

- Engineering route: `FEATURE` because the change affects review behavior,
  GitHub CI signaling and several project-governance boundaries, without
  changing product architecture or runtime behavior.
- User authorization: the user required functional/code risk to take priority
  over comments and PR formatting, requested fewer user-audit hard locks before
  E7, and asked the accepted PR #13 staggered workflow to support continuous
  development.
- Selected route: all PRs keep hard CI, security, contract and affected-behavior
  checks; formatting and documentation nits are advisory. E2/E4/E6/E7 are
  combined deep-audit windows, E3/E5 are lightweight asynchronous gates, E2
  user review is asynchronous and due before E4, and E7 is the only planned
  user hard-stop acceptance.
- Track 2 relevance: preserves evidence for the local W7900/ROCm Agent loop,
  RAG/permission/privacy boundaries and submission claims while reducing
  low-value review latency.
- Evidence/submission impact: routine PRs retain traceable checks/risk/rollback;
  deep-audit milestones, GPU gates, performance work and final claims retain
  full sanitized packets.
- Non-goals: no product feature, hidden blind fixture/score, model/runtime,
  dependency, deployment, external publication or production change.
- Residual risks and controls:
  - Defects in E3/E5 may be found later when their private cases are bundled
    into E4/E6. Their affected public functional/contract tests remain hard,
    concrete Critical/High signals trigger immediate escalation, and work
    cannot cross the next deep-audit promotion gate with unresolved blockers.
  - E2 asynchronous user feedback may cause bounded E3 rework. It does not
    block E3 after the technical gate, but any product-direction finding must
    be resolved before E4 promotion.
  - Advisory PR metadata can be incomplete. Deep-audit/competition/GPU/RAG or
    permission work still requires full mapping and evidence; reviewers judge
    the diff and linked evidence rather than treating a green advisory as
    product acceptance.
- Verification: shell and Python syntax `PASS`; 32 public unit tests `PASS`;
  contract/disclosure gate `PASS`; workflow YAML parse and diff whitespace
  checks `PASS`. No Radeon Cloud runtime claim is made by this governance-only
  change.

### 2026-07-28 PR #17 deduplication proposal

- Engineering route: `PATCH`; the user requested removal of the LangGraph plan's
  duplication after PR #16 integrated the real E2 workflow.
- Scope: one E3–E8 LangGraph evolution plan plus one task-specific `spec` link.
  Current status, acceptance criteria, milestone cadence, E2 conformance,
  evidence policy and competition rules stay in their existing authorities.
- Track 2 relevance: preserves incremental planning, RAG, Runtime permission,
  durable recovery and exact W7900 evidence requirements without maintaining
  fourteen competing copies of them.
- Evidence/submission impact: documentation-only; repository gates and a clean
  diff are sufficient. No GPU, product capability or milestone promotion is
  claimed.
- Rollback: revert the deduplication commit; PR #16 product code and accepted
  evidence are unaffected.

### 2026-08-01 E2/E3 W7900 competition-evidence verification

- Verification route: `Kinnyu Verify`; evidence-only acceptance against exact
  clean `main@60503eb91c403dc9bdcbc00de6064561d2600cdd`.
- Track 2 relevance: both runs used the local `Qwen2.5-14B-Instruct` model
  through ROCm vLLM on one Radeon PRO W7900 48 GB profile, bound to
  `127.0.0.1`. Model Tool Calls remained proposals; deterministic Runtime
  policy granted or denied execution.
- E2 result: `PASS`. Serving Reference S1 retained one warm-up and three
  successful measured calls. Vertical Slice V1 proved ingest, edit/autosave,
  pause, process restart, resume, one real model call, one inert Tool Call,
  Runtime `ALLOW`, tool `SUCCEEDED`, verification `VERIFIED`, current-source
  retrieval, `COMPLETE_WITH_GAPS`, and restoration after a second restart.
- E3 result: `PASS`. The gate passed remote/ROCm checks, full model-snapshot
  SHA-256, native Tool Call, model contract, Runtime allow/deny/restart, M2
  integration regressions, one real semantic extraction call, source-linked
  timeline roles, and correction-driven invalidation/regeneration.
- Integrity/privacy result: every manifest artifact hash matched; the sanitized
  packets had no credential, authorization header, email, host name, device
  serial, raw private prompt, or raw private response match.
- Regression result: the same exact-main W7900 checkout passed the complete
  Agent `pytest` suite (206 tests) and `ruff check .`; the repository-only
  shell syntax, Python compilation, 34 public QA tests and contract gate also
  passed on the evidence branch.
- Evidence paths:
  `evidence/milestones/e2-m1-w7900/20260801T094735Z/` and
  `evidence/milestones/e3-m2-w7900/20260801T093210Z/`. Raw append-only records
  remain under `/workspace/amd-track2-agent/evidence/` and are not committed.
- Evidence-tool limitation: the E3 gate's venv guard resolves the interpreter
  symlink outside the venv. The run used a byte-identical Python interpreter
  copied into the existing Agent venv to satisfy that guard; the Agent
  dependencies and product code were unchanged. This is a runner-path issue,
  not a product-function failure, and should be repaired before the next clean
  reproduction.
- Unverified/non-claims: E2 S1 did not measure streaming TTFT or sampled peak
  VRAM; neither packet is the new Stage 1 `S0` freeze, a Candidate comparison,
  a concurrency result, `A0`, or an optimization claim. Human UI/product
  acceptance remains a separate gate.

### 2026-08-03 performance-plan design verification

Verdict: `PASS — DESIGN READY FOR IMPLEMENTATION`; this verifies the benchmark
contract, not AC-31/AC-32 execution or product acceptance.

| Focus | Method | Evidence | Status | Remaining risk |
|---|---|---|---|---|
| Stage 1 causal service screen | Contract/diff review against AC-31 and current AMD/vLLM guidance | `SERVING_BENCHMARK_ENGINEERING_PLAN.md` Sections 2–4, 7 and 10–11 | PASS | On-Pod development-wheel CLI/backend flags still require capability capture |
| Stage 1 optimization, not only comparison | Prospective selection-rule review | Eight factor profiles plus at most one mechanically selected composite and optional non-blocking GGUF probe | PASS | Quantization Bonus eligibility/support is not promised |
| Stage 2 business fitness | Matrix and score reproducibility review against AC-32 | Seven weighted fixtures, 7+6/13-flow schedule, A0 dedup/bookend, exact components, gates and evidence files in Section 5 | PASS | Complete Agent/A0 and real Stage 2 evidence do not exist yet |
| Contest evidence and deadline recovery | Evidence/timebox/rollback review | Append-only packet layout, Builder/Scorer split, UTC+8 control points and BF16 fallback | PASS | Pod availability and application freeze can still consume schedule buffer |
| Privacy and judging | Data-boundary and disagreement review | Public/synthetic/de-identified-only judge, deterministic veto, swapped order and human adjudication | PASS | External judge provider/model must be frozen before use |
| Repository regression | Required repository checks plus link/fence/credential/diff review | 34 public QA tests, contract gate, shell/Python syntax and document checks | PASS | No runtime benchmark code was expected or executed in this design PR |

The next gate remains `STAGE1_READY`: implement SB1–SB3, reproduce the runner
from a clean checkout, verify `S0` load/rollback on W7900, freeze hashes and
demonstrate scorer behavior on synthetic evidence. AC-31 and AC-32 remain
`NOT VERIFIED` until the corresponding real evidence runs finish.

### Changed files

| File | Change | Reason |
|---|---|---|
| `docs/kinnyu/L3_ENGINEERING_PLAN.md` | Added bounded Agent architecture, split E1 checkpoints, early serving reference, frozen input identities and contest cut-line | Resolve the post-E0 competition-risk review before any E1 merge or milestone promotion |
| `docs/kinnyu/CURRENT_ITERATION.md` | Recorded selected choices, revised status and next gate | Keep the approved requirement source aligned with L3 without claiming product verification |
| `docs/kinnyu/HANDOFF.md` | Replaced the stale pre-merge E0 checkpoint with the current risk-hardening state | Give teammates and future Agents the exact continuation boundary |
| `docs/team-alignment/AGENT_ARCHITECTURE.md` | Defined the single orchestration Agent, local RAG, tools, memory, Runtime and verification loop | Make all five Track 2 capability targets concrete and reviewable |
| `docs/COMPETITION_READINESS_CHECKLIST.md` | Added the single T00–T16 competition task board plus member, capability, demo, submission, model/evidence and cut-line gates | Give the owner one status route from current PRs to submission and prevent a completed product from still missing eligibility or delivery proof |
| `docs/COMPETITION_REQUIREMENT_COVERAGE.md` | Mapped official hard requirements, scoring, submission materials and non-requirements to T00–T16 evidence and current gaps | Distinguish planned coverage from implemented proof and prevent both omission and contest-driven scope creep |
| `spec/README.md` and current status surfaces | Replaced the obsolete PR #9 merge blocker with the live PR #10 → #7 → #8 dependency gate | Keep teammate Agents aligned with merged requirements and prevent green CI from being mistaken for acceptance |
| `docs/COMPETITION_READINESS_CHECKLIST.md` | Added a dated recovery window, function freeze, submission rehearsal and a safer internal submission deadline | Make schedule slippage visible and cut optional scope before correctness or evidence is sacrificed |
| `config/models/*`, `config/runtime/*`, `scripts/verify_model_snapshot.py`, `scripts/verify_vllm_tool_call.py` | Frozen proposed model/runtime identities and added fail-closed verification helpers | Prevent nightly/model drift while preserving the real-current-pod evidence boundary |
| `scripts/install_vllm_rocm721.sh`, `scripts/serve_vllm.sh`, `.env.example` | Removed latest-nightly discovery and made the proposed profile target the frozen snapshot while refusing missing or mismatched local files | Make the E1 environment reproducible without claiming the snapshot or E1-A3 gate already passed |
| `qa/tests/test_model_snapshot_verifier.py` | Added public pass/fail/path-safety tests for the model manifest verifier | Prove the new fail-closed behavior without exposing private QA |
| `spec/EVIDENCE_RETENTION.md` and `evidence/README.md` | Added mandatory storage-tiered history and evidence packet contract | Make every teammate Agent retain review/demo/submission proof while building |
| `spec/README.md`, `spec/AGENT_ALIGNMENT.md`, `README.md` | Routed every task through the evidence contract | Make the rule visible before proposals and implementation |
| `.github/pull_request_template.md` | Added packet path, storage tier, commit and supersedes fields | Require evidence handoff at every PR without exposing private scoring |
| `docs/team-alignment/TEAM_QUALITY_CONTRACT.md`, `docs/team-alignment/BENCHMARK_PLAN.md` | Added append-only milestone and Benchmark evidence lifecycle | Prevent best-run selection or final-week reconstruction |
| `AGENTS.md`, `spec/README.md`, `spec/AGENT_ALIGNMENT.md` | Made L3 and competition obligations part of every teammate Agent's mandatory alignment | Turn readable requirements into an enforceable start-of-task gate |
| `.github/ISSUE_TEMPLATE/engineering_work_package.md`, `.github/pull_request_template.md` | Added product/quality/Track 2/evidence mapping to Issue and PR handoff | Keep future development bounded and reviewable |
| Product, L3, Agent, competition and quality contracts plus `qa/scripts/check_retrieval_phase.py` | Split current-source grounding from post-M4 candidate discovery and user-confirmed historical detail, then added AC-30 and an executable public trace gate | Prevent early-history anchoring and keep teammate Agents, implementation and quality review aligned to the clarified RAG order |
| `docs/DEVELOPMENT_ENVIRONMENT.md`, competition status, handoff and `evidence/milestones/e1-a3-remote-environment/*` | Recorded sanitized current-pod SSH, quota, GPU and ROCm observations while keeping model/runtime claims unverified | Turn remote access/device recovery into reviewable Track 2 evidence without falsely promoting E1-A3 |

### Commands and results

| Command / action | Result | Evidence |
|---|---|---|
| `git diff --check` | PASS | No whitespace errors in the L3 revision |
| `bash -n scripts/*.sh` | PASS | Required repository shell syntax check |
| `python3 -m py_compile scripts/*.py` | PASS | Required repository Python syntax check |
| `bash -n qa/gates/*.sh qa/perf/*.sh` | PASS | Public QA shell syntax remains valid |
| `python3 -m py_compile qa/scripts/*.py qa/tests/*.py` | PASS | Public QA Python helpers compile |
| `python3 -m unittest discover -s qa/tests -v` | PASS — 31 tests | Public QA, model-snapshot and RAG phase-order verification tests, including no-match and relation-decline outcomes, have no regression after the contract hardening |
| `bash qa/gates/pr_gate.sh --mode contract` | PASS | Credential/disclosure boundary and seven public fixture contracts remain valid; no product AC falsely passed |
| `python3 -m json.tool evidence/templates/manifest.example.json` | PASS | Evidence Manifest example is valid JSON |
| Local JSON parse and Markdown-link check across the changed authority/entry files | PASS | New evidence/spec/schema links and JSON contracts resolve and parse locally |
| Diff secret/private-contact scan | PASS | No credential pattern, collaborator email or private-QA payload appears in the proposed change |
| Current-pod public-key SSH and `sshd -t` | PASS | OpenSSH server installed after explicit user approval; password login remains disabled |
| Current-pod quota, `/workspace`, GPU and ROCm inspection | PASS / CONDITIONAL | 16-core CPU quota, approximately 55 GiB memory quota, 98 GiB `/workspace`, one `gfx1100`/96-CU/49136-MB GPU and ROCm 7.2.1 observed; identifiers and network details excluded from Git |
| Historical current-pod PyTorch/vLLM/project check | HISTORICAL — NOT VERIFIED / BLOCKED (SUPERSEDED) | At the time of this failed check, the replacement `/workspace` had no project checkout and system Python had no `torch` or `vllm`, so E1-A3 was not yet accepted. Preserve this row as failure evidence; PR #12/T06 later accepted the exact-current-commit W7900/ROCm/14B packet at `evidence/milestones/e1-combined/20260727T055758Z/`, superseding this old gate conclusion without deleting it |

### Debug notes

- PR #4 originally used a `NEEDS_EVIDENCE` route value not represented in the
  frozen public schema. The revision preserves the four public values and uses
  `BLOCKED` plus a deterministic reason code for missing evidence.
- The original fully serial E1-E8 rule prevented both developers from working
  concurrently. The approved L3 first used paired A/B work packages; the
  accepted PR #13 plan replaces E2–E7 with one accountable owner plus bounded
  adjacent-stage preparation; promotion still requires independent quality
  review.

### Scope changes

- Contract and reproducibility hardening inside the approved P0 and
  contest-delivery scope. It adds public verification helpers and configuration
  manifests but no product application behavior, hidden threshold, dependency
  installation, model download, infrastructure mutation, deployment or
  external publication.
- The clarified RAG order changes no P0 audience, output or permission scope.
  It tightens when cross-asset data becomes available and makes the previously
  implicit user-confirmation boundary executable through AC-30.

## 15. Verification

| Acceptance criterion | Status | Evidence | Remaining risk |
|---|---|---|---|

- Verdict: `PASS` for the E1 combined gate/T06 after PR #12 review and merge;
  there is no M1–M5 or full-product acceptance verdict.
- Verified at E1 scope: 31 public QA tests, 58 backend tests, 89 frontend tests,
  contract provenance, build/lint/typecheck, 15 mock browser paths and 16
  live-loopback paths pass. Four injected local-model failure classes now
  persist explicit terminal results and survive repository restart. PR #7
  review accepted the earlier exact-commit E1-A3 W7900/14B Runtime packet; the
  current `de72a6c` correction also passes a fresh exact-current-commit
  W7900/ROCm/14B Tool Call and Runtime rerun.
- Not verified: M1-M5 product behavior, complete user journey,
  OOM-specific model-service recovery, or performance Baseline/Candidate.
- Out-of-scope change review: Not applicable.
- Recommended next action: create one bounded E2 Issue for the M1 Experience
  Brief vertical slice with contract/schema+fixture, runnable backend/UI
  vertical-slice, and evidence/promotion checkpoints. After the E2 technical
  gate, provide an asynchronous product review whose feedback is resolved
  before E4 promotion.

## 16. New Ideas Captured

- B-001 Idea Asset path
- B-002 Method Asset path
- B-003 Advanced relation graph and method promotion
- B-004 Direct external publishing
- B-005 Additional output renderers
- B-006 Multimodal ingestion
- B-007 Fine-tuning or distillation
- B-008 Multi-user collaboration

## 17. User Acceptance

- Decision: PENDING
- Notes: Requirement contract is approved; product acceptance occurs only after implementation and verification.
- Accepted by:
- Date:

## 18. Quality Framework Engineering Checkpoint

The user separately approved hardening the quality/benchmark framework before
any product milestone is accepted. Its bounded FEATURE proposal, implementation scope,
checkpoint criteria, and evidence are recorded in
`docs/kinnyu/iterations/2026-07-24-quality-framework-hardening.md`.

This checkpoint does not resolve the material product-engineering choices in
Section 13 and does not change any AC-01..AC-30 status. It makes their future
verification paths executable while preserving the public/private evaluation
boundary.

- Quality framework engineering status: IMPLEMENTED
- Quality framework verification status: PASS
- Quality framework iteration status: CLOSED / USER ACCEPTED
- Evidence: `docs/kinnyu/iterations/2026-07-24-quality-framework-hardening.md`

## 19. PR #18 Proportional-Standard Repair (2026-07-28)

- Route: `PATCH` — documentation and governance behavior only.
- Outcome: replace the duplicated 630-line proposal with one compact routing
  standard and a seven-point entry checklist.
- Review resolution: add a lightweight route for bounded low-risk work; allow
  prospectively declared, versioned E8 Candidates while preserving an
  immutable Baseline, frozen quality floors, comparability, and rollback; route
  the full standard only to affected work instead of requiring every small
  Agent task to read it.
- Track 2 relevance: preserves stronger review and evidence for Agent, privacy,
  W7900/ROCm, benchmark, milestone, demo, and submission changes while reducing
  low-value review blocking elsewhere.
- Evidence/submission impact: no new product or GPU claim; repository checks
  and resolved documentation links are sufficient for this patch.
- Non-goals: no application behavior, API/schema, dependency, milestone
  promotion, benchmark result, deployment, or hidden-QA change.
- Rollback: revert the final PR #18 repair commit; no data migration or external
  state restoration is required.

## 20. PR #22 E4/M3 W7900 Unblock (2026-08-01)

- Route: `PATCH` — repair the approved E4/M3 implementation without expanding
  product scope.
- Product objective: persist a truthful decision/evidence ledger from the local
  W7900 model, including an explicit `NEEDS_INPUT` result when the source lacks
  claim-level evidence.
- Track 2 relevance: restores the local Qwen/vLLM/ROCm path and keeps model
  output subordinate to Runtime schema, evidence, permission, and identity
  validation.
- Evidence/submission impact: the exact candidate commit must pass repository
  checks and the E4 W7900 gate; append-only packets remain under
  `/workspace/amd-track2-agent/evidence/e4-m3-w7900/`.
- Non-goals: no new milestone, cross-asset RAG, remote core-model API, public
  tunnel, benchmark claim, model training, or product-scope change.
- Acceptance: guided output is structurally complete; regeneration targets the
  exact affected decision; declared-moment evidence is validated as a union;
  fully unresolved but explicit proposals persist as `NEEDS_INPUT` rather than
  fabricating evidence or failing storage; structured extraction uses greedy
  decoding to avoid sampling-driven acceptance instability; only an explicit,
  timestamped user confirmation may promote an unreferenced gap to a supported
  `SELF_REPORTED` judgment.

## 21. E7 Deterministic Delivery Isolated Implementation (2026-08-02)

- Route: `FEATURE`, implementing Issue #30 on
  `codex/e7-deterministic-delivery` from the open PR #28 head
  `a0b042d812d1358814b3f7743a58541e653acff0`.
- Engineering status: `IMPLEMENTED`; isolated verification status:
  `ISOLATED_READY_CANDIDATE_PENDING_INDEPENDENT_REREVIEW`; integration and user
  acceptance remain pending.
- Initial implementation commit:
  `ca53e8d5b1c11bf2e55cfe54f64d62bbfb20dd57`; independent-review fix commit:
  `3d5cd02428a5d291bb7919a21a8b0ca0ab0c1b28`.
- Product result: one saved Chinese-or-English canonical RouteDraft envelope
  now drives private preview, self-contained HTML, editable Markdown and
  canonical JSON with one exact asset/version/hash/lineage/relation/route/
  language/privacy/renderer identity. Draft-content hash, relation projection
  and renderer input are distinct. Supersession is explicit and historical
  rows and files are not silently overwritten.
- Permission result: private in-app preview does not require external approval;
  external-audience export fails closed unless the frozen E6 adapter validates
  an exact E6-issued ApprovalRecord and E7 input snapshot. The adapter consumes
  a fixture generated by E6's real helper and does not recompute or weaken its
  composite binding hash. It is not live E6 service integration.
- Deletion result: deletion requires a persisted request plus separate second
  confirmation, locks the asset, records per-file effects, exposes partial file
  or SQLite failure, supports restart-safe retry and retains a content-free
  terminal audit state. Expired unconfirmed requests become audited `EXPIRED`
  terminal records and no longer block a replacement request.
- Boundary result: no canonical domain model, OpenAPI, shared migration,
  repository implementation, API root or `web/src/App.tsx` change. The preview
  component remains feature-scoped until the shared integration window.
- Verification: 238 Python tests, 34 public QA tests, 136 frontend tests and 16
  executable browser tests passed; Ruff, contract provenance, shell/Python
  syntax, disclosure/credential gate, typecheck, ESLint and production build
  passed. Four existing live-backend browser cases were skipped by their
  declared environment gate.
- Evidence: `evidence/milestones/e7-review-fixes/20260802T062138Z/` supersedes
  the earlier readiness packet, records the two independent-review blockers,
  their fixes, real-E6 helper reproduction, commands, non-claims and rollback.
- Unverified/non-claims: real E6→E7 integration, shared API/repository/app-root
  wiring, W7900/ROCm/vLLM, complete product closure, deployment and external
  publication. The code still requires review by another teammate or an
  independent Codex session before acceptance.
- Rollback: normally revert
  `ca53e8d5b1c11bf2e55cfe54f64d62bbfb20dd57`; no shared migration or external
  side effect needs reversal.
