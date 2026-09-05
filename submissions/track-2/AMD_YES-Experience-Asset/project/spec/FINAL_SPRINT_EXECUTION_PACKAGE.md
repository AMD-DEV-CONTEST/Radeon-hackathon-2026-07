# Final Sprint Execution Package — 2026-08-05

## Status, authority, and deadline

- Status: **OWNER-APPROVED / EFFECTIVE IMMEDIATELY**
- Effective date: 2026-08-05 AEST
- Official deadline: **2026-08-06 23:59 UTC+8**
- Scope: E5–E9 integration, application Baseline, Stage 2 evaluation, evidence,
  and final submission assets
- Track 2 relevance: direct. This package preserves the complete local Agent
  loop, Radeon PRO W7900/ROCm proof, business quality, performance evidence,
  and reproducible submission materials while removing final-day review waits.

This is the single execution entry point for the remaining contest work. It
supersedes older instructions that require a separate private blind-test run,
quality-owner promotion, or synchronous human approval between E5, E6, E7,
E8, and E9. It does **not** weaken product behavior, privacy, Runtime policy,
local-inference, evidence, or competition requirements.

This owner instruction is operationally effective even while its documentation
PR is awaiting merge. Merge the documentation promptly when safe, but do not
turn that merge into a new prerequisite for the E5–E8 integration lane.

The owner has directed the team to disclose all previously planned evaluation
requirements. Repository review confirmed that no executable private test
suite, private fixture payload, Gold Answer, secret score, or unpublished pass
threshold was ever implemented. The full evaluation intent that exists is
published below. No developer must wait for a hidden result.

Secrets, credentials, private user data, raw private prompts, and model caches
remain prohibited from Git. “Publish all tests” does not authorize publishing
sensitive data.

## One-page execution board

| Owner | Deliver now | Completion boundary | Next handoff |
|---|---|---|---|
| **Kali / Khalil (`@1olaqua616-web`)** | Integrate E5, E6, and E7; make the complete user path work; freeze the complete-Agent commit; run and retain the E8 `A0` application Baseline on the canonical W7900 | One functional-freeze integration PR plus a complete Baseline/evidence packet; no unresolved Critical/High product defect | Exact frozen application commit, Baseline manifest, commands, evidence paths, and known limitations to the owner and Ethan |
| **Owner / `@kinnyuww`** | Preserve and hand off the frozen Stage 1 service evidence; after Kali freezes `A0`, run Stage 2 Candidate Evaluation | Stage 1 finalists remain frozen; Stage 2 selects one application profile or explicitly keeps `A0`; all claims use retained evidence | Frozen finalists now, then selected profile, comparison table, chart-ready data, and limitations to Ethan |
| **Ethan / Lian (`@Eas000n`)** | Build E9 final deliverables in parallel; continuously consume existing evidence; finalize after the `A0` and Stage 2 handoffs | English Project Specification, reproducible README, 3–5 minute video, PPT or poster, evidence index, and official submission PR are complete and link-valid | Final submission checklist and timed rehearsal |

### Dependency line

```text
Owner Stage 1 ───────────────┐
                             ├─> frozen finalists
Kali E5 → E6 → E7 → A0 ─────┼─> Owner Stage 2 ──> selected profile/evidence
                │            │                              │
                └────────────┴────────> Ethan E9 drafts ───┴─> final package
```

Ethan starts immediately. Ethan must not wait for final numbers before writing
the Project Specification, README, architecture diagrams, video storyboard,
slide structure, reproducibility section, or evidence index.

## GitHub audit correction — 2026-08-05

This section records the final read-only audit of the remote repository before
execution. It corrects stale status language without converting an isolated
branch, local test packet, or planning PR into a completion claim. Refresh the
remote refs before integration if any listed head has moved.

- `origin/main` is `335f798c853263a2220d992d9e85f5fe5f9b7862`. PRs
  #36, #38, and #32 are in `main`; PR #37 merged into the still-open PR #28
  branch and is not in `main`.
- E5 PR #40 is at `e3ff011` and contains PR #35 at `60c1ec2`. Its deterministic
  packet proves the disclosed local/fake GraphRAG cases, not real-model or
  W7900 completion. E5 T11, the external W7900 exact-head local-inference gate,
  remains outside that packet.
- E6 PR #31 is at `8f03f3c`, remains Draft and `CHANGES_REQUESTED`, and has no
  live E5/SQLite/production-LangGraph/API/App/restart integration. Its latest
  fixes have not received a formal follow-up review.
- E7 PR #34 is at `31df834`. Its expired-deletion and E6-approval-hash fixes
  make it an `ISOLATED_READY` candidate pending focused recheck, not accepted
  or integrated E7.
- Stage 1 PR #39 is frozen at `e22d8da` with `STAGE1_COMPLETE` in its latest
  retained checkpoint. Stage 2 was not run and no product default changed.
- PR #44 is a 20K qualification plan at `4e806ab`; its runtime work was not
  executed. E8 has no frozen `A0`, and GitHub has no E9 final-deliverable PR.

Use the following words literally:

| State | Meaning |
|---|---|
| Code written / tests green | The named checks passed at the named head; predecessor integration and device claims remain separate |
| `ISOLATED_READY` candidate | Feature-owned behavior works against frozen contracts or equivalent fixtures and still needs focused acceptance/recheck |
| `INTEGRATION_READY` | The real predecessor, SQLite, Runtime/LangGraph, API, App, restart, and affected checks pass at one exact head |
| W7900 evidence complete | The named exact-head local-inference run and its hashes/manifest are retained; a fake or CPU run cannot qualify |
| Merged complete | Accepted behavior and evidence are merged into `main`; an open Draft PR is never described this way |

The audit also found stale or conflicting text. PR #41 still describes an old
E5/E6 sequence; the PR #35 body predates work now carried by #40; the PR #39
body contains older partial checkpoints before its final completion comment;
and Issue #43's 8K wording predates the approved-business-budget versus
verified-capability split below. Do not spend final-day capacity repairing each
historical record. Apply the current behavior and preserve the old record as
history.

## Final-day collaboration rule

There is no longer a stage-by-stage owner-approval loop.

1. Work continues inside the assigned lane after local self-verification.
2. Kali may consolidate E5–E7 in one integration branch/PR and continue into
   the `A0` Baseline without waiting for separate E5/E6/E7 approvals.
3. Ethan may prepare all E9 material in parallel and replace placeholders when
   frozen evidence arrives.
4. PRs are progress logs and merge boundaries, not requests for synchronous
   permission to begin the next internal step.
5. Required CI, targeted functional checks, evidence, and secret scanning still
   run. A passing format template is not a substitute for working behavior.
6. Documentation, comment, wording, naming, or PR-template imperfections do not
   block. A reviewer should patch those directly or record them as backlog.
7. If a code defect is found, report one consolidated checklist with the
   observable failure and minimum fix. Do not create repeated review cycles for
   new cosmetic preferences.

Replace the former full cross-audit loop with one consolidated integration-diff
review and two narrow no-self-review checks:

- the owner checks only E6 privacy/approval policy and W7900 evidence;
- Ethan checks only E7 canonical hashes, approval staleness, export, deletion,
  and retry behavior; and
- one independent teammate or coding Agent checks the consolidated diff against
  this public matrix and the repository standards. A coding-Agent review
  qualifies only when a non-author teammate initiates it or signs off on its
  findings.

These are review surfaces, not stage-start approvals. They block only when they
identify one of the substantive failures below. Nobody approves their own
implementation, and the normal reviewed merge boundary remains.

Only substantive product, safety, locality, evidence, or competition failures
may stop integration or submission, including:

- broken primary user flow or schema/API incompatibility;
- loss, overwrite, or incorrect restoration of confirmed user state;
- fabricated material fact or silent conflict resolution;
- privacy, export approval, tool-permission, or phased-RAG bypass;
- core/private inference outside the local W7900/ROCm/vLLM path;
- crash, timeout, OOM, or tool failure without a visible terminal state and
  retained failure record;
- irreproducible or hash-inconsistent competition evidence;
- secret, credential, private-user-data, or prohibited raw-evidence disclosure;
- failure of required CI/public contracts, eligibility, licensing, or an
  official submission requirement;
- a demo or final deliverable that materially misstates what the product did.

When an infrastructure failure prevents a W7900 run, retain the failure and
continue every non-GPU task. Do not mislabel a fake/local run as W7900 proof.

## Frozen product outcome

Turn a person's fragmented experience into a persistent, evidence-aware,
reusable Experience Asset, then produce only the audience-specific outputs
supported by that evidence.

The refinement experience is the main product, not a hidden preprocessing
step. The user must see useful, editable progress from the first response.

### Required end-to-end user journey

1. Accept conversation, pasted text, or `.txt`/`.md` input.
2. Create and autosave an editable `Experience Brief v0.1`.
3. Produce M2 `Critical Moment Map` without silently merging conflicts.
4. Produce M3 `Decision and Evidence Ledger`, separating source fact, user
   judgment, Agent inference, and unresolved information.
5. Produce M4 `Insight and Boundary Map` with evidence, counterfactuals,
   limits, counterexamples, and transfer conditions.
6. Bind `KnowledgeCardReady` to the exact M4 version/hash.
7. Only after readiness, search approved local **summaries** for possible
   relations. No match or user decline is a successful visible outcome.
8. Only after the user confirms one relation, retrieve that selected asset's
   detailed evidence. Historical content never silently rewrites current facts.
9. Evaluate five routes: private/self, beginner, peer,
   customer/evaluator, and public. Explain `READY`, `BLOCKED`, or `INELIGIBLE`.
10. Surface privacy/claim risks and let the user keep, generalize, or remove
    them. An external-audience shareable export requires explicit approval
    bound to exact version/hash, route, language, risk state, and renderer.
11. Preview and export Chinese or English HTML, Markdown, and canonical JSON
    from the same version/hash. A newer export supersedes the old one.
12. Support pause, restart, resume, correction/invalidation, and idempotent
    confirmed deletion with visible failure/retry behavior.

### Interaction contract

- Ask one to three highest-value questions per round and say why they matter.
- Allow edit, skip, defer, pause, resume, or continue with visible gaps.
- Never fabricate an ETA. Determinate progress is allowed only for known work
  units; otherwise show the actual milestone, saved version, completed
  artifacts, unresolved items, and route readiness.
- A correction creates a traceable new version and invalidates only dependent
  artifacts, readiness, approval, retrieval, preview, and export records.
- Model output is a proposal. Runtime owns tool allowlists, argument
  validation, approvals, timeouts, retries, execution, verification, and audit.

## Kali execution contract — E5 to E8 Baseline

### 1. Integrate, do not rebuild in parallel

- Start from current `origin/main` and inventory the active E5, E6, and E7
  branches/PRs before editing.
- Reuse accepted implementations and resolve overlap in one integration branch.
- Preserve API/schema compatibility with E1–E4 and checked-in contracts.
- Run dependency/checkpoint migrations explicitly; do not copy only endpoint
  files while omitting persistence, schema, tests, or evidence capture.
- Keep the application and vLLM environments separate and all private services
  loopback-bound.

Use the remote branches as implementation sources, not as already accepted
milestones:

- take E5 from PR #40 as one stack; it already contains PR #35, so do not merge
  #35 and #40 as two sequential release gates;
- replay the E6 feature diff from PR #31 and exclude its PR #28 baseline merge
  commit instead of blindly cherry-picking the merge history;
- replay the E7 feature/fix diff from PR #34 and recheck its two previously
  reported blockers at the integrated head; and
- retain PR #28's substantive state, permission, phased-RAG, and handoff
  semantics without importing its stale review cadence as a product
  dependency. PR #41, PR #42, and PR #44 do not need to merge first, but the
  E6 consumer facts recorded in #42 must be applied.

### 2. E5 / M4 must work

Observable requirements:

- `Insight and Boundary Map` links lessons, evidence, counterfactuals,
  limitations, counterexamples, and applicability conditions.
- `KnowledgeCardReady` is an explicit, version/hash-bound decision.
- Before readiness: cross-asset candidate discovery is denied.
- After readiness: discovery reads only approved summary cards and returns the
  candidate plus a relation reason, or a visible no-match result.
- Before relation confirmation: detailed historical retrieval is denied.
- After confirmation: detail is limited to the selected relation/asset.
- Historical retrieval cannot mutate current Experience Asset statements.
- Decline, correction, readiness invalidation, retry, and resume are durable.

E5's real-model compatibility probe and T11 external W7900 exact-head
local-inference evidence may share the same device window. The retained record
must still identify which observations satisfy each acceptance boundary: one
schema-valid positive proposal, one semantic hard-negative, and the exact E5
schema compatibility result. Sharing a run removes duplicate setup; it does
not erase either check.

Keep two context numbers separate:

- `20480` tokens is the approved business budget ceiling for tokenized input
  plus reserved output; and
- `8192` tokens is the only context window currently verified on the W7900.

Until a larger window passes its own device gate, `A0` uses the verified 8K
service configuration and deterministic trimming/chunking. Do not describe 8K
as the product's permanent business limit, and do not describe 20K as verified
deployment capability. PR #44's 20K qualification is outside the critical path.

### 3. E6 / M5 must work

- Produce all five `RouteDecision`s and a visible `Route Readiness Matrix`.
- Preserve route-specific content contracts; the five routes cannot be five
  tone variants of the same article.
- Mark unsupported professional/customer claims ineligible instead of
  inventing credentials, clients, results, or authority.
- Surface privacy findings with category, affected reference, severity,
  explanation, and `KEEP` / `GENERALIZE` / `REMOVE` actions.
- External shareable output remains blocked until findings are resolved or
  explicitly acknowledged and the exact draft/version receives approval.
- Any bound input change makes that approval stale.

The integrated E6 path must close two audited producer/consumer gaps:

- E5 currently produces no `sensitivity_tags`, while PR #31's deterministic
  detector reads those tags. Use a small general deterministic text detector
  or explicit user-provided privacy proposal that the Runtime validates. If no
  trustworthy proposal source runs, fail closed or require explicit review;
  an empty proposal list must not silently mean that content is risk-free.
- `EvidenceStrength.DIRECT` is not produced by E1–E5. All five route decisions
  must execute, but all five do not have to be `READY`. Preserve a truthful
  `BLOCKED`/`INELIGIBLE` customer/evaluator result unless the live handoff has a
  qualifying `SOURCE_FACT` or grounded inference with the required non-`NONE`
  evidence. Never weaken the predicate or invent `DIRECT` evidence to make the
  matrix uniformly green.

Importing #31's pure policy code is not E6 completion. The final head must use
the real E5 projection and stored E7 draft through SQLite, Runtime/production
LangGraph, API, App, persistence/restart, and exact-bound approval seams.

One generic version/hash-bound approval mechanism is acceptable; five separate
approval engines are not required. A privacy-pending route may use `BLOCKED`
with a deterministic reason rather than a separate internal fourth enum.

### 4. E7 delivery must work

- Store user-selected Chinese or English route drafts.
- Provide a user-facing preview plus self-contained HTML, editable Markdown,
  and canonical JSON generated from one canonical route draft.
- Prove the format outputs share the same canonical version/hash.
- Mark prior exports `SUPERSEDED` when a newer export is created.
- Implement second-confirmation deletion, idempotency, and one representative
  visible partial-failure/retry path.
- Direct external posting/emailing remains out of P0.

Thin deterministic renderers are acceptable. Separate renderer architectures
per route and an exhaustive injected filesystem failure matrix are not
deadline requirements.

At the integrated head, specifically recheck that an expired deletion request
does not permanently lock an asset and that E6 recomputes the same canonical
approval binding/hash used by E7. Green isolated tests or a fix author's own
evidence do not substitute for this focused recheck.

### 5. User-facing complete path

The Baseline must be exercisable through the actual product surface, not only
isolated domain methods. The flow may use the current React UI plus API, or a
documented temporary operator path only when a UI element is genuinely missing;
every missing user-facing action must be named in the Baseline limitation list.
The submission demo needs one coherent visible path, so a CLI-only final result
is not sufficient.

### 6. Freeze `A0 Application Baseline`

After the complete path is green:

- freeze exact application commit, prompts, fixture inputs/expected terminal
  states, Runtime policy, database seed, retrieval index, renderer, generation
  settings, model profile, and evidence directory;
- use the known-good local BF16/S0-compatible service; frozen Stage 1 finalists
  feed only the owner's Stage 2 comparison and never replace `S0` in the `A0`
  freeze;
- run all seven public fixtures once, preserving complete failures;
- run one recorded complete W7900 flow demonstrating local inference,
  plan/retrieve/tool/verify/persist/deliver, allow/deny, restart/resume, privacy
  approval, phased RAG, and final rendering;
- write append-only raw/large evidence under `/workspace/amd-track2-agent` and
  push small sanitized evidence and report-ready summaries to Git immediately;
- execute `bash scripts/pre_stop_checkpoint.sh` before risky tests, leaving the
  Pod, or destroying/replacing the instance.

Handoff to the owner must include exact commit SHA, all launch/test commands,
manifest/hash files, evidence paths, observed terminal states, failures,
limitations, rollback command, and the clean-checkout reproduction result.

## Owner execution contract — Stage 1 and Stage 2

### Stage 1 frozen; Stage 2 waits for `A0`

The final Stage 1 checkpoint at `e22d8da` records Qwen3.5-9B on the W7900,
all five confirmation profiles passing all nine retained hard gates, and the
ranking `P1 > P4 > S0 > P3 > P2`. Retained P1 warm-up reliability and W1/W4
format failures remain limitations. This is a service-layer result only: it
does not select the application profile, change the product default, or prove
the complete Agent flow.

The serving benchmark contract, profiles, workloads, gates, scores, results,
and evidence format remain frozen by
`docs/kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md`. This sprint package does
not change a measured profile, weight, gate, workload, or result after viewing
evidence.

Retain the completed Stage 1 record as follows:

1. Freeze the run group and compute hashes.
2. Preserve every failure, timeout, crash, retry, and rollback.
3. Push code plus small sanitized manifests, gate reports, score components,
   ranking, chart data, and a human-readable report to Git before the Pod can
   be lost.
4. Keep raw logs, model caches, sensitive records, and large traces outside Git
   under `/workspace/amd-track2-agent`, with approved backup where possible.
5. Hand the exact finalist profile IDs/configs to Kali and record whether S0
   remains required as fallback.

### Stage 2 after Kali freezes `A0`

- Do not start before the complete application commit and Baseline inputs are
  immutable.
- Always evaluate `A0 = complete Agent + S0`, plus each unique Stage 1 finalist.
- Keep application code, prompts, Runtime policy, fixtures, database seed,
  retrieval index, renderer, and generation settings identical across profiles.
- Eligibility: seven fixtures once per profile.
- Confirmation for passers: two additional clean runs each for complete,
  correction, and resume; 13 measured flows per passing profile.
- Run A0 first and a final unscored complete-flow bookend. A >10% TTFA or
  end-to-end drift, or changed deterministic outcome, invalidates timing
  comparison until investigated.
- Product failures are not retried away. One transient infrastructure retry is
  allowed and remains labeled.
- Hard business/safety gates override speed and numeric score.
- Select one profile or explicitly retain A0; publish the raw/indexed component
  table, exclusions, drift result, failures, launch/rollback commands, and
  chart-ready sanitized summary.

If Stage 2 cannot finish safely before submission assembly, use the known-good
S0 profile, retain Stage 1 as service-layer optimization evidence, and record
one complete W7900 Agent flow. Never call an unfinished comparison a product
ranking.

## Ethan execution contract — E9 final deliverables

### Start immediately with placeholders

At the audit snapshot, GitHub contains the E9 access/queue requirement from PR
#38 but no final-deliverable implementation PR. Do not implement the optional
public queue/tunnel merely to satisfy that requirements document. The recorded
demo and clean local reproduction route are the deadline path.

Create and continuously update:

- English Project Specification;
- reproducible English README and clean-checkout commands;
- architecture and complete Agent-loop diagram;
- evidence/claim index that maps every sentence about locality, performance,
  reliability, privacy, RAG, or task success to a retained artifact;
- timed 3–5 minute video storyboard/script and shot list;
- PPT or poster; and
- final official-repository PR checklist and correct PR title.

Use explicit placeholders such as `PENDING_A0_SHA` or
`PENDING_STAGE2_SELECTED_PROFILE`; never invent metrics or silently leave a
placeholder in the final package.

### Required story and evidence

The materials must show, using real retained evidence:

1. the user problem: invisible personal experience is hard to reuse;
2. the first useful artifact and progressive M1–M4 refinement;
3. fact/judgment/inference/unresolved separation and visible correction;
4. post-M4 summary-only relation discovery, user confirmation, then bounded
   detailed RAG;
5. five-route readiness, one ineligible route, privacy review, approval, and
   audience-specific delivery;
6. one structured model tool proposal followed by Runtime validation,
   allow/deny, bounded execution, actual-result verification, and persistence;
7. pause/restart/resume and a visible failure or safe stop;
8. local W7900/ROCm/vLLM proof with exact model/profile and loopback service;
9. measured Baseline-versus-Candidate results with sample counts, failures,
   latency/throughput/VRAM/task-success definitions, and rollback; and
10. HTML/Markdown/JSON output consistency and user-facing preview.

### Required submission set

- English Project Specification.
- Complete source and reproducible README.
- 3–5 minute demo video with English narration or subtitles.
- PPT or poster.
- Evidence index and sanitized evidence links.
- Official competition PR using the required English title convention.
- Three-person eligibility/account/team/GitHub/Discord consistency checked by
  the owner; never place private registration details in Git.

A live public demo is optional. Do not expose vLLM, SSH, a database, or an
unauthenticated WebUI. If the authenticated queue/tunnel cannot be verified,
submit a reliable recorded demo and local reproduction route instead.

## Fully disclosed functional evaluation matrix

The following replaces every former reference to undisclosed variants or a
separate blind gate. These are developer-visible requirements and may be used
directly during implementation.

| Case | Must happen | Must never happen |
|---|---|---|
| Complete | Reach M1–M5; label material statements; mark customer/evaluator ineligible without qualifying context; public share waits for approval; render consistent outputs | Unsupported fact, copied identity/verbatim source, automatic publication, or historical silent rewrite |
| Incomplete | Ask or visibly mark missing high-value detail; explain why the question matters; permit bounded continue/skip/defer | Invent a second item, final decision, result, or convert inference into fact |
| Conflicting | Surface the conflict and request confirmation; retain both claims as unresolved until resolved | Silently choose, merge, or store one timeline as source fact |
| Privacy risk | Surface identity/location/third-party/purchase and relevant metadata risks; offer keep/generalize/remove; block external share until resolution/acknowledgment plus approval | Auto-redact without decision, publish automatically, or issue a shareable link before approval |
| Route ineligible | Give a concrete reason and mark thin routes low-readiness/blocked/ineligible | Invent professional/client context or a confident guide from thin evidence |
| Correction | Create a traceable new version; apply changed duration/outcome; invalidate and regenerate affected downstream artifacts | Retain stale content, silently revert, overwrite history, or reuse stale approval/export |
| Resume | Continue from last durable checkpoint; preserve confirmed facts, artifacts, relations, and history; invalidate readiness when the card changes | Restart from scratch, lose confirmed state, or drop prior versions |

### Public adversarial and failure checklist

All are now visible and may be automated:

- input/retrieved prompt injection cannot change Runtime policy, tool registry,
  permissions, retrieval phase, or local-inference boundary;
- unknown tool, invalid arguments, unapproved export, destructive action
  without confirmation, and detailed RAG before relation confirmation are denied;
- cross-asset retrieval before M4 readiness is denied while current-source
  grounding remains available;
- no-match, relation decline, route ineligibility, `needs_input`, and `safe_stop`
  count as correct terminal states when expected;
- schema/tool-proposal error gets bounded retry and then a visible terminal
  failure; no infinite loop;
- timeout, model unavailability, OOM, SQLite/tool/filesystem error, and user
  interruption retain the last durable version and a traceable terminal state;
- repeated submission and confirmed deletion are idempotent;
- correction invalidates only dependent artifacts and stale approvals;
- HTML, Markdown, JSON, preview, and export all identify the same canonical
  version/hash;
- private data never reaches a shared/remote model API;
- core model traffic stays loopback-local on the Radeon Cloud W7900/ROCm path;
- every claimed run identifies code, model/profile, environment, fixture,
  seed/order, terminal outcome, failures, and evidence hashes.

### Acceptance mapping

The full matrix covers `AC-01` through `AC-32`. In particular:

- refinement and user control: `AC-01`–`AC-17`;
- complete Track 2 Agent loop: `AC-18`;
- reproducible local/performance evidence: `AC-19`–`AC-21`, `AC-31`, `AC-32`;
- proportional review and seven disclosed cases: `AC-22`–`AC-25`;
- prospective optimization, promotion safety, overload, and versioning:
  `AC-26`–`AC-29`;
- phased, confirmed, non-contaminating historical retrieval: `AC-30`.

For this final sprint, the old private portions of `AC-23`, `AC-25`, `AC-27`,
and `AC-29` are satisfied by this full disclosure plus public reproducible
checks. They do not create an additional promotion gate.

## Required commands and evidence minimum

Run repository checks for every integration/final-deliverable branch:

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
git diff --check
```

For Agent behavior:

```bash
source /workspace/amd-track2-agent/venvs/agent/bin/activate
pytest
ruff check .
```

On Radeon Cloud:

```bash
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
```

Run the milestone/artifact gate with the real output, progress record, and M4/M5
retrieval trace when those files exist. Also run the project-specific E5–E7 and
browser/E2E commands introduced by the integrated code; the integration PR
must list their exact invocations rather than rely on this document guessing
future filenames.

Each final-sprint PR includes:

- outcome and exact commit;
- affected ACs and E5/E6/E7/E8/E9 boundary;
- commands and observed results;
- sanitized evidence paths/hashes;
- W7900 status (`PASS`, `NOT_RUN_INFRA_BLOCKED`, or `NOT_APPLICABLE`);
- known failures/limitations and their submission impact;
- secret/private-data scan result; and
- rollback commit/command.

## Git, persistence, and handoff

- GitHub is the source of truth for code and small sanitized evidence.
- `/workspace/amd-track2-agent` is the working location for models, venvs,
  large/raw evidence, logs, caches, and local data. PVC is not a backup.
- Push every coherent tested checkpoint before GPU stress, handoff, leaving the
  Pod, or destructive/rebuild operations.
- Never develop directly on `main`, force-push, commit credentials, or hide a
  failed run.
- A teammate may continue preparing the next internal task inside the assigned
  final-sprint lane; this exception removes approval waiting, not branch safety.
- Use one integration PR for Kali's E5–E8 Baseline lane and one E9 PR/branch for
  Ethan's submission lane where practical. Avoid a new PR per small document or
  sub-step.

## Stop conditions

Stop new feature work when the complete path, A0, and submission narrative are
credible. Prefer a known-good profile and reliable recorded demo over a late,
unmeasured model swap, public tunnel, second base model, fine-tune, custom GPU
kernel, elaborate multi-Agent system, or nonessential UI polish.

The final decision question is simple: can a judge reproduce and observe a
useful private Agent complete the task from clarification to safe delivery on
one local W7900, and can every performance/reliability claim be traced to real
evidence? If yes, package and submit; if no, fix that path before any cosmetic
work.
