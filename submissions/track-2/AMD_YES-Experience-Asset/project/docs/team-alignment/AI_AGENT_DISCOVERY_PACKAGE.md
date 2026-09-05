# AI Agent Discovery Package — Experience Asset P0

## Operating instruction

You are receiving the completed product-discovery package and current E1
boundary. Reconstruct and acknowledge the approved product before suggesting or
continuing work. Engineering authority comes only from the assigned Issue and
current integration gate, not from this summary alone.

Authority order:

1. `docs/kinnyu/CURRENT_ITERATION.md` — approved P0 requirement and acceptance criteria
2. `docs/kinnyu/PROJECT.md` — durable goal and boundaries
3. `docs/kinnyu/BACKLOG.md` — explicitly deferred ideas
4. `AGENTS.md` — repository, persistence, security, and Git rules
5. this package — concise alignment aid

If this package conflicts with a higher-authority file, follow the
higher-authority file and report the conflict.

## Product in one sentence

Turn a person's fragmented lived experience into a persistent, evidence-aware,
reusable Experience Asset, then generate only the audience-specific products
that the evidence supports.

## Product emphasis

The refinement experience is the primary P0 value, not an invisible step that
prepares a publishing screen. The first response should already make the raw
experience easier to see. Later questions selectively recover the context,
critical moments, decisions, evidence, uncertainty, and applicability that make
the experience reusable.

## Why it exists

People remember conclusions but lose the context, alternatives, actions,
evidence, uncertainty, and boundaries that make experience reusable. A summary
alone is insufficient. The product helps the user clarify the experience over
time, exposes ambiguity before finalization, and keeps one canonical source for
all later views and exports.

## Approved P0 user journey

1. The user supplies conversation, pasted text, or `.txt`/`.md` material.
2. The Agent produces an editable, autosaved `Experience Brief v0.1` and identifies the highest-value missing or conflicting information.
3. The user moves through five visible, resumable refinement milestones and reviews the artifact produced by each one.
4. After M4, the user confirms the current Knowledge Card or explicitly accepts
   its visible gaps. Until then, cross-asset RAG is blocked.
5. The system may then show summary-only candidates from approved local assets;
   only a user-confirmed relation unlocks detailed historical retrieval.
6. The system saves a versioned canonical Experience Asset without silently
   importing historical claims into the current facts.
7. It evaluates five audience routes: private/self, beginner, peer, potential customer/evaluator, and public.
8. It generates only eligible routes and explains why another route is ineligible.
9. The user previews the selected Chinese or English route.
10. HTML, Markdown, and JSON are rendered from the same canonical version.
11. Public export is blocked behind privacy/claim review and explicit final approval.

## Refinement milestones and artifacts

| Stage | Agent focus | User-visible artifact |
|---|---|---|
| 1. Boundary and goal | Source provenance, event boundary, user goal, constraints, obvious sensitive material | `Experience Brief v0.1` |
| 2. Timeline and critical moments | Ordered events, changes, cues, surprises, and turning points | `Critical Moment Map` |
| 3. Decisions, actions, results, evidence | Alternatives, reasons, actions, observations, and statement status | `Decision and Evidence Ledger` |
| 4. Lessons, counterfactuals, boundaries | What would change next time, support, limitations, counterexamples, and transfer conditions | `Insight and Boundary Map` |
| 5. Route readiness and approval | Audience eligibility, missing support, privacy/claim review, and delivery preview | `Route Readiness Matrix` |

Between stages 4 and 5, `KnowledgeCardReady` is bound to the exact M4
version/hash. Candidate discovery reads only approved summary cards. Detailed
cross-asset evidence remains unavailable until the user confirms a relation.
No-match or decline is a successful, visible outcome; it does not block M5.

Interaction rules are contractual:

- normally ask one to three highest-value questions per round;
- state why each requested detail matters;
- allow answer, edit, skip, defer, pause, resume, or generation with current evidence;
- acknowledge concrete completed work, not generic praise or pressure mechanics;
- show actual milestone, confirmed facts, unresolved questions, route readiness,
  current version, and autosave state;
- use a determinate percentage only for known work units;
- never fabricate progress or an ETA; an ETA requires comparable run history and
  must be a range with uncertainty;
- reopening a stage preserves the prior version and explains why it reopened.

Useful elicitation targets include situation and goal, critical incidents,
noticed cues, alternatives, decisions, actions, observed results, surprises,
counterfactuals, evidence strength, sensitive details, and applicability
boundaries. Preserve distinctions between what happened, what the user judged,
what the Agent inferred, and what remains unknown.

## Canonical asset contract

The asset must preserve:

- source references and provenance;
- context, goal, and constraints;
- alternatives, decisions, and actions;
- observed results and evidence;
- extracted lessons and applicability boundaries;
- audience, route eligibility, and maturity;
- versions and user-confirmed relations to other assets;
- statement status: source fact, user judgment, Agent inference, or unresolved.

The Agent must never convert an inference into a fact merely to improve the
story. Insufficient evidence produces a question, warning, or ineligible route.
Historical retrieval never retroactively changes current-experience statements;
incorporation requires an explicit user edit, a new version and provenance.

## Primary test fixture

Use an anonymized, paraphrased adaptation of the public office-chair comparison
at `https://www.reddit.com/r/OfficeChairs/comments/hem1s7/`.

The fixture represents a person who:

- tried an Aeron for roughly two weeks;
- observed advantages such as cooling and appearance but experienced personal discomfort;
- exchanged it for a Leap V2 and tried that for roughly two weeks;
- preferred the Leap's comfort and adjustability despite aesthetic/ventilation trade-offs;
- learned that fit is individual and return policy/testing conditions matter.

Do not copy the post, username, exact body measurements, or other identifying
details. Mark the fixture as adapted public research, not first-party testimony.
The final competition demonstration should use an explicitly authorized real
experience where practical.

Expected fixture routing:

| Route | Expected result |
|---|---|
| Private/self | Personal decision record and future purchase checklist |
| Beginner | First ergonomic-chair trial guide grounded in this experience |
| Peer | Evidence/boundary-aware comparison of the two trials |
| Customer/evaluator | Ineligible unless qualifying professional/client context is supplied |
| Public | Publish-ready “why I switched” experience, after privacy approval |

## Privacy and approval boundary

Before an external-audience shareable export, surface risks involving identity, body/health, location,
purchase/payment data, third parties, screenshot metadata, copyright,
unverified brand claims, and professional-advice implications. Let the user
keep, generalize, or remove each finding. Export remains blocked until findings
are resolved or acknowledged and final approval is explicit.

External publishing, messaging, and emailing are not P0 capabilities. Deletion
requires a second confirmation and immediately removes only product-managed
copies; external copies cannot be recalled.

## Technical and operational boundaries

- Core inference must run locally on the Radeon Cloud W7900 through ROCm.
- P0 uses one durable LangGraph orchestration Agent with visible
  plan/retrieve/tool/verify/persist behavior; see `AGENT_ARCHITECTURE.md`.
- vLLM owns model serving; the Agent runtime owns state, policy, validation, approvals, retries, and audit.
- Model tool output is a proposal, never permission.
- Private experience data must not be sent to shared remote model APIs.
- `/workspace` is persistent working storage; GitHub is the source of truth for source code.
- Do not expose raw vLLM or infrastructure services publicly.
- Do not implement on `main`; wait for an approved engineering proposal and use a task branch.

## Competition and benchmark contract

The formal Track 2 rules remain authoritative. The team also treats the Track 2
presentation's judging guidance as a required evidence target: “local” and
“faster” claims must be verifiable, and a reliable Agent must complete the task
from clarification through delivery, adjustment, or safe stop.

Benchmark three layers independently:

1. **Model server:** TTFT, output tokens/s, latency, peak VRAM, errors, and
   concurrency behavior.
2. **Agent task:** end-to-end latency, model-call count, task completion,
   terminal state, tool error/recovery, evidence coverage, unsupported claims,
   privacy and route correctness.
3. **Refinement UX:** time to first useful artifact, question burden,
   milestone completion/resumption, correction recovery, route readiness, and
   user-rated clarity/progress/control/trust.

Each run must retain the exact hardware/software/model/configuration/fixture
manifest. Baseline and Candidate use the same task and measurement method; the
Candidate declares its intended model/quantization/context/serving/workflow
delta before measurement and all non-declared conditions remain frozen. Use
warm-up and repeated runs; keep failures; report sample size, mean/median/p95
where applicable, and failure rate rather than a best-case number.

ROCm fit means using and proving the exact supported W7900/ROCm/vLLM path,
establishing a stable BF16 baseline, then measuring changes to context budget,
GPU-memory utilization, batching/concurrency, prefix caching, prompt/call count,
quantization, attention backend, or vLLM optimization level. CUDA/FA2 recipes
are not assumed to work. Every experiment needs a known-good rollback profile.

The detailed contract and artifact layout are in `BENCHMARK_PLAN.md`.

## Quality-control boundary

`TEAM_QUALITY_CONTRACT.md` is active. Every teammate and coding Agent must
implement that public contract and provide its requested evidence pack.
The quality owner maintains a separate blind-evaluation system.

The stage preferences are versioned defaults rather than frozen implementation
recipes. A teammate may propose a component-specific metric or optimization
change before evaluating a Candidate, with business rationale, baseline
evidence, quality floors, side effects and rollback. It takes effect only after
quality-owner approval and may not be tailored to private blind-test results.

Do not request, search for, read, infer, create substitutes for, or commit:

- hidden test code or private fixture variants;
- gold/private expected outputs;
- exact quality weights, pass thresholds, aggregation, seeds, or case-selection
  logic;
- any `private-qa`, `.qa-private`, `benchmarks/private`,
  `benchmarks/hidden`, or `data/quality-owner-private` material.

The Agent should optimize the approved business behavior, not a guessed answer
key. Public performance evidence remains reproducible; only internal business-
quality scoring stays blind.

## P0 exclusions

- Idea Asset and Method Asset end-to-end paths
- raw image/audio/video understanding
- automatic web research as unreviewed evidence
- direct external publishing
- multi-user collaboration
- medical, legal, financial, or safety advice
- training or fine-tuning before a measured working baseline

## Current status

- Requirement: APPROVED
- Engineering proposal: APPROVED
- Product implementation: E1_ACCEPTED_E2_ISSUE_PENDING — PR #7, PR #8,
  PR #12 and PR #13 are accepted and merged at `main@b053f66`
- Promotion status: T06 is `PASS`; M1–M5 remain unverified
- Verification: PASS at E1 combined scope; the exact `de72a6c` implementation
  commit passed the accepted W7900/ROCm/14B Tool Call and Runtime rerun
- Acceptance criteria: AC-01 through AC-30 in `CURRENT_ITERATION.md`
- Approved execution plan: `docs/kinnyu/L3_ENGINEERING_PLAN.md`
- Current integration hold: create the bounded E2 Issue from
  `docs/kinnyu/E2_E8_PIPELINE_EXECUTION_PLAN.md`. The accepted current E1
  packet is `evidence/milestones/e1-combined/20260727T055758Z/`; both prior
  packets remain retained. E1-A1, E1-A2 and E1-A3
  remain separately traceable checkpoints inside Issue #5 / PR #7, not three
  Issues. Later E2–E9 work remains gated; if the plan review passes, create one
  E2 Issue with three auditable checkpoints and permit only bounded
  preparation of the immediately adjacent stage.

## Required alignment response

Before proposing work, respond with exactly these six headings:

1. **Product objective** — restate the one observable user outcome.
2. **P0 flow** — list the input-to-export stages in order.
3. **Evidence and permission boundaries** — state what the Agent must never assume or do.
4. **In scope / out of scope** — distinguish current work from Backlog.
5. **Acceptance mapping** — identify which AC IDs your proposed area would affect, including refinement UX (AC-15–17), the complete Agent loop (AC-18), benchmark evidence (AC-19–21), and quality governance (AC-22–29) where relevant.
6. **Questions or conflicts** — report only genuine blockers; write `None` if aligned.

Do not produce code, task estimates, architecture changes, commits, or external
actions as part of this alignment response.
