# E6/M5 Route Readiness, Privacy, and Approval Specification

- Status: `PROPOSED / PR28-CONTROLLING / ISOLATED IMPLEMENTATION AUTHORIZED /
  SHARED INTEGRATION BLOCKED`
- Date: 2026-08-01 AEST
- Owner: `Eas000n`
- Quality and integration owner: `kinnyuww`
- Work item: GitHub Issue #29
- Execution authority for this work package: PR #28 at `a0b042d`,
  `E5_E7_PARALLEL_EXECUTION_CONTRACT.md`, and GitHub Issue #29
- Machine-readable checkpoint:
  `contracts/checkpoints/e6-m5-contract-fixtures-v1.json`
- Product scope: complete E6/M5; no PR #26 scope reduction applies

This specification turns the approved E6/M5 outcome into an implementable,
reviewable contract. The user explicitly selected PR #28 as controlling for
E5-E7 execution wherever it conflicts with the older sequential pipeline. It
does not claim E6 completion, change an accepted `AC-*`, authorize a
shared-schema edit, or permit shared-entry integration ahead of E5. Repository
promotion still waits for PR #28 merge and the required independent reviews;
this file is an E6 proposal rather than a new source of product authority.
Checkpoint 1 uses automated checks plus asynchronous teammate/Codex review. It
does not reintroduce an intermediate synchronous user-approval lock and does
not block the isolated modules, mocks, fixtures, tests, or feature UI allowed
by PR #28.

## 1. Observable outcome

For the exact current Experience Asset version, a user can inspect a truthful
`Route Readiness Matrix` covering all five routes, see the evidence and missing
support behind every decision, review privacy and claim risks, choose an
allowed resolution for each finding, and explicitly approve an exact final
external-audience draft. Preview, generation, and private download never imply
approval. Any bound content, route, language, risk-resolution, draft, or render
input change makes the prior approval unusable.

E6 is complete only when this behavior is durable, restart-safe, visible
through the real application boundary, and independently accepted after live
E5 integration. Isolated mocks and fixtures may prove `ISOLATED_READY`, but
cannot prove `INTEGRATION_READY`, substitute for the live E5-to-E6 handoff, or
support any claimed W7900 run.

## 2. Authority and interpretation decisions

The following sources remain authoritative, in order:

1. `CURRENT_ITERATION.md` for P0 and `AC-*`;
2. `L3_ENGINEERING_PLAN.md` for architecture and complete E6 scope;
3. PR #28 and `E5_E7_PARALLEL_EXECUTION_CONTRACT.md` for E5-E7 ownership,
   parallel isolation, integration, and promotion; these control over the
   older sequential execution rule where they conflict;
4. `E2_E8_PIPELINE_EXECUTION_PLAN.md` for unaffected evidence, gate, and
   delivery rules;
5. `AGENT_ARCHITECTURE.md` and `LANGGRAPH_ADOPTION_PLAN.md` for Agent, Runtime,
   graph, permission, privacy, and persistence boundaries;
6. this specification for the E6 implementation details below.

Two interpretations are required to remove cross-stage ambiguity. They are
recommended here and must be explicitly confirmed at Checkpoint 1:

### 2.1 Frozen symbol meaning, not frozen future field shape

`KnowledgeCardReadiness`, `RelationCandidate`,
`RelationCandidateDecision`, `RouteDecision`, `PrivacyFinding`,
`ApprovalRecord`, `RouteDraft`, and `ExperienceAssetV1` keep their existing
authority and meaning. E5 may still perform the synchronized schema extensions
already required by the accepted PR #23 GraphRAG specification. E6 and E7 may
not create competing domain types or privately fork the shared vocabulary.

### 2.2 RouteDraft before a real ApprovalRecord

E6 owns approval policy, binding validation, persistence, idempotency, and
stale-approval invalidation. E7 owns generation and persistence of the final
Chinese or English `RouteDraft` and invokes the E6 approval service after the
user reviews that exact draft. A valid `ApprovalRecord` is created only after
the final draft exists and before any `SHAREABLE_EXTERNAL_EXPORT`.

E6 isolated tests may use a stored fixture `RouteDraft`, but may not present a
fixture approval as a complete user journey. This preserves the formal merge
order: the E6 policy/service can merge before its E7 caller, while the real
approval/export journey is accepted only after E7 and the combined chain pass.

## 3. Scope

### 3.1 Required in E6

- evaluate all five routes for the exact current canonical version;
- emit all four eligibility states with deterministic reasons;
- persist and display a `RouteReadinessMatrixV1`;
- produce source/statement-bound privacy and claim-risk findings;
- support `KEEP`, `GENERALIZE`, `REMOVE`, and `ACKNOWLEDGE` only where allowed;
- distinguish risk discovery, user resolution, route eligibility, preview,
  private download, approval, and external export;
- provide a deterministic, version/hash-bound approval service for every
  external-audience route;
- invalidate stale route decisions, findings, drafts, and approvals after any
  relevant change;
- extend the production LangGraph with M5 route, privacy, wait/resume,
  approval, verification, and safe-terminal transitions;
- preserve local inference, Runtime permission, durable state, privacy, audit,
  and failure evidence;
- cover complete, privacy-risk, route-ineligible, and correction scenarios.

### 3.2 Explicit non-goals

- no reduction to three eligibility states or fewer than five route decisions;
- no generation of HTML, Markdown, JSON, or final RouteDraft in E6;
- no automatic external publication, messaging, email, or social posting;
- no model-controlled permission, approval, persistence, or policy override;
- no independent E6 copy of E5 relation state or detailed historical content;
- no new remote model API, vector database, or second canonical datastore;
- no medical, legal, financial, safety, or universalized professional advice;
- no claim that automated privacy review guarantees all risks were found;
- no E8 Baseline or performance-optimization claim.

## 4. E5-to-E6 read-only handoff

E5's sidecar relation ledger is the only persistence authority for candidate,
decision, confirmation, and invalidation state. E6 consumes an
application-composed, read-only projection of that ledger, or a
contract-equivalent mock before E5 merges. The following list is a consumer
requirement, not a new durable DTO and not permission to bypass E5 repositories:

| Required input | Meaning |
|---|---|
| `asset_id` | Current Experience Asset identity |
| `version_id` and canonical content hash | Exact immutable version being evaluated |
| lineage/current-pointer result | Proof that the version is still current |
| `KnowledgeCardReadiness` | Exact ready or accepted-with-gaps M4 binding |
| current statements and evidence status | Only canonical, current-version facts, judgments, inferences, and unresolved items |
| M2/M3/M4 structured records | Critical moments, decisions, actions, results, evidence, insights, limitations, counterexamples, and applicability |
| unresolved questions | Missing material remains visible and cannot be converted into support |
| relation outcome | Exactly `NO_MATCH`, `DECLINED`, `CONFIRMED_RELATION`, or `STALE` |
| confirmed relation context | Only for `CONFIRMED_RELATION`: relation IDs and evidence references that E5 Runtime currently authorizes |
| relation-context validity | Whether confirmed relation evidence is still current and permitted |
| policy/workflow/schema identities | Inputs to audit, invalidation, and reproducibility |

E6 does not need to reproduce every E5 UI state. `NO_MATCH` and `DECLINED`
both mean that M5 may continue without historical support. A confirmed relation
may contribute only its explicitly permitted evidence references. `STALE` is a
fail-closed handoff outcome: it blocks route evaluation until E5 emits a current
projection, and it cannot expose historical evidence. E5 remains responsible
for presenting `RUNNING`, `TECHNICAL_FAILURE`, `STALE`, candidate, decline,
confirmation, and detail-access behavior.

Relation candidates, decisions, confirmations, and historical content are not
embedded in immutable `ExperienceAssetV1` snapshots and must never change the
current asset content hash. The read-only projection may compose relation state
for an application response, but it is not a second write authority.

The handoff fails closed when:

- readiness does not bind the exact current version and hash;
- the current pointer or lineage changed;
- a historical reference is not backed by a current persisted confirmation;
- a relation or evidence reference is stale, missing, or outside E5 permission;
- required policy/workflow/schema identity is absent.

Failure produces a safe visible M5 blocked/invalidated state. It never triggers
new cross-asset discovery and never reads additional history.

## 5. Route decision contract

### 5.1 Five routes and four states

Every evaluation returns exactly one `RouteDecision` for each:

- `PRIVATE_SELF`;
- `BEGINNER`;
- `PEER`;
- `CUSTOMER_EVALUATOR`;
- `PUBLIC`.

Allowed eligibility states:

| State | Meaning |
|---|---|
| `ELIGIBLE` | Required content support exists and no unresolved share/privacy gate remains for the intended operation |
| `ELIGIBLE_AFTER_PRIVACY_APPROVAL` | Content support exists, but one or more external-share findings require user resolution or acknowledgement before approval |
| `BLOCKED` | The route could become usable for this experience, but required support, current state, or a recoverable technical/policy prerequisite is missing |
| `INELIGIBLE` | The current experience lacks a defining qualifying context for the route and the system must not manufacture it |

Decision precedence is deterministic:

1. invalid/stale M5 input produces `BLOCKED`;
2. missing defining route context produces `INELIGIBLE` where the route
   contract explicitly requires that context;
3. missing support or unresolved evidence produces `BLOCKED`;
4. sufficient content plus open applicable privacy/share findings produces
   `ELIGIBLE_AFTER_PRIVACY_APPROVAL` for an external route;
5. otherwise the route is `ELIGIBLE`.

The model may propose a claim-to-route mapping, but cannot select the final
state. Deterministic policy validates the route contract, canonical references,
evidence status, missing support, and privacy state.

For `peer_evidence` and `verifiable_result`, a current statement with
`EvidenceStrength.NONE` never qualifies. Peer evidence may use a non-`NONE`
`SOURCE_FACT`, or an explicitly confirmed `USER_JUDGMENT`/`AGENT_INFERENCE`.
A verifiable result is stricter: it accepts a `DIRECT`/`INDIRECT`
`SOURCE_FACT`, or a confirmed and derived `AGENT_INFERENCE`; a self-reported
judgment alone does not qualify. An E5-authorized historical statement ID is
accepted only after the confirmed-relation gate that exposed it.

### 5.2 Route-specific minimum policy

| Route | Required support | Required failure behavior |
|---|---|---|
| `PRIVATE_SELF` | Decision record or unresolved decision context; personal lesson or open lesson; uncertainty retained; next-time considerations derivable from confirmed material | Missing core decision/lesson support → `BLOCKED`; privacy findings remain visible but do not turn private review into external approval |
| `BEGINNER` | At least one supported action/lesson, prerequisites or starting conditions, ordered guidance basis, common mistake/risk, and non-applicability boundary | Missing evidence or boundary → `BLOCKED`; no universal advice or invented prerequisite |
| `PEER` | Alternatives or failed attempt, evidence strength, trade-off/constraint, and limitation/counterexample | Missing comparison/evidence structure → `BLOCKED`; uncertainty may not be removed for a cleaner narrative |
| `CUSTOMER_EVALUATOR` | Explicit qualifying professional/project/client role or context, goal, method/action, verifiable observed result, and limitation | Missing qualifying context → `INELIGIBLE`; qualifying context present but result/support incomplete → `BLOCKED` |
| `PUBLIC` | Supported event arc, transferable lesson, applicability boundary, uncertainty/disclosure basis, and no unsupported professional/universal claim | Missing support/boundary → `BLOCKED`; open external-share finding → `ELIGIBLE_AFTER_PRIVACY_APPROVAL` |

Only the selected eligible route is generated later. E6 evaluation of five
routes is not permission to generate five polished outputs.

### 5.3 Reason codes v1

The following codes are the proposed E6 v1 vocabulary. Checkpoint 1 must accept
or revise them before they enter shared API/schema contracts:

| Code | Use |
|---|---|
| `M5_INPUT_NOT_READY` | Exact M4 readiness is absent |
| `M5_INPUT_STALE` | Version/hash/current-pointer or relation context is stale |
| `MISSING_DECISION_OR_LESSON` | Private route lacks its minimum useful decision/lesson basis |
| `MISSING_BEGINNER_PREREQUISITE` | Beginner starting conditions are absent |
| `MISSING_BEGINNER_GUIDANCE_BASIS` | No supported ordered action/lesson basis exists |
| `MISSING_PEER_COMPARISON` | Alternatives, failed attempts, or trade-offs are absent |
| `MISSING_PEER_EVIDENCE` | Peer comparison lacks source/evidence support |
| `MISSING_QUALIFYING_CONTEXT` | Customer/evaluator role or project/client context is absent |
| `MISSING_VERIFIABLE_RESULT` | Qualifying context exists but a supported result is absent |
| `MISSING_APPLICABILITY_BOUNDARY` | Required limitation, counterexample, or non-applicability condition is absent |
| `MISSING_DISCLOSURE_BASIS` | Public route lacks a supported uncertainty or disclosure basis |
| `UNSUPPORTED_UNIVERSAL_CLAIM` | Proposed route would universalize one experience |
| `UNSUPPORTED_PROFESSIONAL_CLAIM` | Proposed route would present unsupported professional advice or authority |
| `OPEN_PRIVACY_FINDINGS` | Content is supported but external-share findings remain open |
| `PRIVACY_REVIEW_FAILED` | Privacy review failed or is not bound to the current input |
| `ROUTE_REEVALUATION_REQUIRED` | Privacy state changed after the route matrix; recompute all five decisions before approval |
| `ROUTE_MATRIX_POLICY_MISMATCH` | Caller-supplied route decisions differ from a fresh deterministic evaluation |
| `PRIVACY_REVIEW_HASH_MISMATCH` | Caller-supplied privacy state does not match its canonical recomputed hash |
| `PRIVACY_REVIEW_POLICY_MISMATCH` | A correctly shaped/hashed review omits required deterministic findings or carries a forbidden severity/action/resolution |
| `UNKNOWN_SENSITIVITY_TAG` | Canonical input contains a sensitivity tag outside the approved vocabulary |
| `APPROVAL_SCOPE_INVALID` | Stored approval scope is not `SHAREABLE_EXPORT` |
| `APPROVAL_ACTION_INVALID` | Stored approval was not created by `APPROVE_SHAREABLE_EXPORT` |
| `READY` | Route meets the current policy contract |

All non-eligible decisions contain at least one code. `supporting_statement_ids`
include only exact current canonical statement IDs or E5-authorized historical
evidence references represented through the approved view. `missing_statement_ids`
include only existing unresolved/unsupported statement IDs. A missing concept
with no statement ID is represented by a reason code and user-visible
explanation; the implementation must not invent an ID.

## 6. Privacy and claim-risk contract

### 6.1 Finding categories v1

The E6 v1 category vocabulary is:

- `IDENTITY`;
- `HEALTH_BODY`;
- `LOCATION`;
- `PURCHASE_PAYMENT`;
- `THIRD_PARTY`;
- `SCREENSHOT_METADATA`;
- `COPYRIGHT`;
- `UNVERIFIED_BRAND_CLAIM`;
- `PROFESSIONAL_ADVICE`.

Every `PrivacyFinding` must have at least one affected statement or source
reference, severity, a user-readable explanation, allowed proposed actions,
the run that created it, and a current resolution. A finding with an unknown
reference, category, action, or stale version is rejected rather than silently
stored.

### 6.2 Detection and authority

Risk discovery uses layered evidence:

1. existing canonical sensitivity tags and source metadata;
2. deterministic category-specific detectors where reliable;
3. optionally, one structured local-model proposal for semantic risks such as
   unverified brand claims, third-party exposure, or professional advice;
4. deterministic Runtime validation of every proposed category, reference,
   action, identity, scope, and schema.

The authoritative review builder always runs layer 1 before merging any
additional detector/model proposals. An empty proposal list therefore means
"no additional proposals", never "skip canonical tag detection". Findings are
deduplicated by category and exact affected references after applying the
deterministic severity floor. An unknown canonical sensitivity tag fails
closed with `UNKNOWN_SENSITIVITY_TAG`; it is never silently discarded.

The local model cannot mark the review complete, choose a user resolution,
grant approval, or declare content safe. Model unavailability, malformed
output, or failed validation produces `PRIVACY_REVIEW_FAILED` and blocks
external approval; it is not interpreted as zero findings. The UI states that
automated review assists but does not guarantee complete detection.

### 6.3 Resolution semantics

| Action | Meaning and effect |
|---|---|
| `KEEP` | Preserve the exact content after an explicit user choice; the residual risk remains visible and must be allowed by policy |
| `ACKNOWLEDGE` | Record explicit acceptance of a permitted residual risk without implying that the risk disappeared |
| `GENERALIZE` | Replace sensitive specificity through a validated user edit, create a new canonical version, and invalidate downstream state |
| `REMOVE` | Remove the affected content through a validated user edit, create a new canonical version, and invalidate downstream state |

`GENERALIZE` and `REMOVE` are canonical correction commands, not in-place
finding-state edits. The old asset version, finding, route decision, and
approval remain historical. The new version must repeat readiness as required,
re-evaluate affected routes, produce a new privacy-review hash, and require a
new approval.

`KEEP` and `ACKNOWLEDGE` are permitted only for categories/severities allowed
by deterministic policy. Critical risks and any category forbidden by the
selected external route cannot be acknowledged around the gate.

### 6.4 Privacy-review hash

The privacy-review hash is SHA-256 over canonical JSON containing:

- asset and exact version identity;
- policy/schema version;
- sorted finding IDs;
- category, severity, affected references, and resolution for each finding;
- the durable resolution/audit identity needed to trace the explicit user
  decision; and
- review terminal state.

Raw private text is not included merely to calculate the hash. Canonical JSON
uses stable key ordering and normalized enum values. Wall-clock time is
retained in audit records but excluded from the state hash so that an
idempotent repeat of the same durable decision does not create a different
binding.

## 7. Approval and operation boundaries

### 7.1 Three different operations

| Operation | Approval behavior |
|---|---|
| `IN_APP_PREVIEW` | Never creates or implies external-share approval |
| `PRIVATE_DOWNLOAD` | Produces a visibly private/self-use artifact and never creates an external-share approval |
| `SHAREABLE_EXTERNAL_EXPORT` | Requires a valid exact-bound approval for beginner, peer, customer/evaluator, or public output |

P0 never publishes externally. Approval authorizes creation of a bounded local
shareable file; it does not authorize posting, messaging, emailing, or network
delivery.

### 7.2 Approval preconditions

The approval service accepts only an explicit user action from the current
local application session and a stored final `RouteDraft`. If a judge-facing
public tunnel is later authorized, that application session must also pass the
approved authentication boundary. The service verifies:

- asset/version/current-pointer and Knowledge Card binding are current;
- the selected external route is `ELIGIBLE`, or
  `ELIGIBLE_AFTER_PRIVACY_APPROVAL` with every finding resolved or permitted
  and acknowledged;
- the selected language matches the final draft;
- the final draft hash is recomputed from its canonical content and generation
  contract identity;
- the privacy-review hash is recomputed from current findings/resolutions;
- required deterministic tag findings, severity floors, allowed actions, and
  non-content resolution states are revalidated so a correctly hashed but
  incomplete caller review cannot become authority;
- the five-route matrix is recomputed from the exact current context and
  privacy review rather than trusting caller-supplied eligibility;
- every referenced statement/evidence item remains current and allowed;
- no blocked, ineligible, stale, failed, or unresolved critical state remains.

Approval creates the existing `ApprovalRecord` fields; it does not add an
unreviewed `renderer_input_hash` field. The `route_draft_hash` must bind all
content and versioned generation/render inputs whose change could alter the
shareable representation. If E7 cannot meet that rule with the existing
`RouteDraft.content_hash`, it must raise a shared-contract gap before
integration rather than silently weakening invalidation.

### 7.3 Validity and invalidation

An approval is usable only when all stored fields equal the current recomputed
values. It becomes stale after any change to:

- canonical asset version/content;
- selected route or eligibility decision;
- language;
- final route draft content or versioned generation/render input;
- finding set, category, severity, affected reference, or resolution;
- privacy policy/schema version where the change affects validity;
- any supporting E5 relation/evidence binding used by the draft.

Stale approval is retained for audit but cannot authorize export. Repeating the
same approval command for the same valid binding is idempotent and returns the
existing record. A conflicting repeated action fails closed and is audited.

## 8. Persistence and state authority

- Immutable Experience Asset versions remain canonical for M1-M5 experience
  content, route decisions, and privacy findings.
- `RouteReadinessMatrixV1` is the M5 milestone artifact bound to the exact
  canonical version and evaluation run.
- The existing same-SQLite approval repository is authoritative for explicit
  approval records and validity checks. Approval must not mutate the content
  hash of the version it approves.
- API views may compose approval references with the current asset, but must
  not create a second approval authority inside LangGraph state or UI state.
- LangGraph checkpoint state contains only bounded IDs, hashes, workflow state,
  attempts, sanitized outcomes, and wait/resume cursors.
- Restart reloads canonical truth and approval state from repositories and
  revalidates every binding before presenting it as current.

If current repository behavior cannot compose approvals without rewriting the
approved version, Checkpoint 1 must record the minimum sidecar/view correction
before implementation. It must not be hidden inside an E6 migration.

## 9. Application services and ports

Names below describe responsibility and may be adapted to repository naming;
they do not create public API paths or new durable domain authorities.

| Component | Responsibility |
|---|---|
| M5 context reader | Compose the authorized current E5/M4 and canonical evidence view |
| Route policy | Deterministically produce five `RouteDecision`s |
| Privacy analyzer | Produce bounded finding candidates from approved local inputs |
| Privacy validator/policy | Validate findings, actions, severity, references, resolution, and export blocking |
| Canonical correction service | Apply `GENERALIZE`/`REMOVE` through a new immutable version |
| Approval service | Create, load, validate, invalidate, and idempotently reuse exact-bound approvals |
| M5 application service | Coordinate evaluation, privacy review, user commands, persistence, verification, and terminal outcomes |

Model-visible tools may propose route evaluation or privacy review only through
the existing allowlisted architecture. Approval mutation, canonical writes,
privacy action execution, and export authorization remain Runtime-only
application commands.

## 10. LangGraph M5 extension

### 10.1 Required responsibilities

The production graph adds only behavior needed for durable, observable M5
orchestration:

1. load and validate the exact M5 context;
2. request/perform route evaluation through deterministic services;
3. run bounded privacy review and Runtime validation;
4. pause for user privacy decisions when needed;
5. apply validated user decisions through application services;
6. re-evaluate after canonical version changes;
7. pause for an exact shareable-approval action when a final draft exists;
8. validate approval binding and stale state;
9. verify and persist a truthful terminal/checkpoint outcome.

The final node names, conditional edges, state schema, workflow version,
topology hash, retry/effect budgets, idempotency keys, and rollback identity are
frozen at Checkpoint 1 after the E5 graph contract is inspectable. Before that
checkpoint, only topology proposals and isolated fakes are permitted.

### 10.2 Graph-state allowlist

Graph state may contain:

- asset/version/run IDs;
- readiness, route-evaluation, privacy-review, and approval binding hashes;
- route/finding/approval IDs;
- current M5 control state and selected conditional edge;
- bounded attempt counts, wait reason, retryability, and safe terminal code;
- workflow/topology/model/policy identity.

Graph state must not contain:

- the canonical Experience Asset JSON;
- raw source text, prompt, response, private finding text, or route draft body;
- a second copy of relation evidence;
- approval booleans supplied by the model or browser;
- renderer output or filesystem paths;
- unrestricted exception payloads.

### 10.3 Required terminals

Every M5 run reaches an existing public terminal such as:

- `SUCCEEDED` when current route/privacy state is durably verified;
- `NEEDS_USER_INPUT` when privacy resolution, missing evidence, or final
  approval action is required;
- `PAUSED` for an explicit user pause;
- `POLICY_BLOCKED` for invalid approval/permission or an invalidated binding,
  with a stable safe reason code;
- `MODEL_UNAVAILABLE`, `INVALID_MODEL_OUTPUT`, `STORAGE_ERROR`, or another
  existing safe failure where applicable.

No new public terminal enum is introduced by this specification without the
normal synchronized contract review.

## 11. Application command semantics

Exact HTTP paths remain owned by API review. The required typed operations are:

- evaluate M5 route readiness for an exact current version;
- read the current Route Readiness Matrix and evidence/missing references;
- start/read privacy review for the exact matrix/version;
- resolve one exact current finding with an allowed user action;
- apply a `GENERALIZE` or `REMOVE` correction with explicit preview/confirmation;
- read current approval readiness and stale reason;
- approve one exact stored external-audience route draft;
- invalidate approval only through a deterministic bound-state change, never
  a client boolean;
- resume/retry a failed or paused M5 run;
- poll/stream real progress and terminal state.

Every mutating command carries expected asset/version/hash and an idempotency
key. Mismatch returns a stable conflict/policy result and performs no partial
effect. The external-approval idempotency key binds both the exact route-draft
hash and privacy-review hash: an exact retry reuses the key, while a changed
privacy review cannot collide with the earlier approval attempt.

## 12. UI contract

The E6 feature UI renders backend-owned state and must provide:

- all five route cards in one Route Readiness Matrix;
- eligibility label, reason, supporting evidence, missing support, and stale
  state for every route;
- an explicit distinction between `BLOCKED`, `INELIGIBLE`, and privacy-pending;
- privacy findings grouped by category/severity with affected references;
- only policy-allowed actions for each finding;
- a warning that automated detection is not a safety guarantee;
- visible canonical version, autosave state, current run, and terminal state;
- explicit confirmation for content-changing `GENERALIZE`/`REMOVE` actions;
- approval readiness, exact route/language/version/draft identity, and stale
  reason;
- visible denial, technical failure, retry, pause, resume, and invalidation;
- no control that implies preview, private download, generation, or a model
  proposal already granted external approval.

Before E5 merges, the feature may use checked-in sanitized mocks and existing
frontend domain symbols only. It may not modify `App.tsx`, invent API state, or
create a competing public type. Live route registration and typed API
regeneration occur during formal E5-to-E6 integration.

## 13. Public fixtures

Fixtures use anonymized, paraphrased, non-private content and preserve the
approved office-chair provenance boundary.

| Fixture | Required behavior |
|---|---|
| Complete | Five decisions; private, beginner, peer, and public follow their route contracts; customer/evaluator is ineligible without qualifying context; all decisions have traceable reasons/support |
| Privacy risk | Identity and health/body risk plus representative claim/copyright risk are visible; external approval is blocked; permitted actions change state correctly; detection disclaimer remains visible |
| Route ineligible | Missing qualifying professional/client context yields customer/evaluator `INELIGIBLE` rather than invented context; other routes remain independently evaluated |
| Correction | A canonical edit changes the version, invalidates affected matrix/findings/draft/approval, preserves the prior version, and requires fresh readiness/evaluation/review/approval |

The isolated E6 branch may use builders over existing domain types. Final JSON,
OpenAPI examples, and frontend fixtures are synchronized only after E5 freezes
and merges the contracts E6 consumes.

## 14. External behavior acceptance matrix

| ID | Behavior | Required result |
|---|---|---|
| E6-01 | Evaluate a current ready complete fixture | Exactly five route decisions and one current matrix are persisted |
| E6-02 | Evaluate before exact readiness | All evaluation is blocked with stable readiness reason; no cross-asset retrieval or approval occurs |
| E6-03 | Evaluate with no-match or declined relation outcome | M5 continues without historical support; no history is invented or required |
| E6-04 | Evaluate with one confirmed valid relation | Only E5-authorized evidence references may support decisions |
| E6-05 | Supply stale/invalid relation context | Historical support is ignored/denied and the stale state is visible |
| E6-06 | Evaluate the chair fixture customer/evaluator route without qualifying context | `INELIGIBLE` with `MISSING_QUALIFYING_CONTEXT` and no invented role/result |
| E6-07 | Omit route-required support while the route could become usable | `BLOCKED` with deterministic reason and honest missing support |
| E6-08 | Evaluate sufficient external content with open findings | `ELIGIBLE_AFTER_PRIVACY_APPROVAL`; approval remains unavailable |
| E6-09 | Detect each public privacy category fixture | Valid findings reference current statements/sources and expose allowed actions |
| E6-10 | Local model emits unknown category/reference/action or extra fields | Runtime rejects the proposal; review does not appear complete or safe |
| E6-11 | Privacy model is unavailable or malformed | Visible retryable/terminal failure; never zero findings by default |
| E6-12 | User applies permitted `KEEP` or `ACKNOWLEDGE` | Durable decision is recorded; residual risk remains visible |
| E6-13 | User applies `GENERALIZE` or `REMOVE` | New immutable canonical version; dependent E5/E6/E7 state becomes stale |
| E6-14 | Attempt an action forbidden for the finding severity/category | Policy denial; no content or resolution change |
| E6-15 | Preview or privately download | No external ApprovalRecord is created |
| E6-16 | Approve without a stored final RouteDraft | Policy denial; no ApprovalRecord |
| E6-17 | Approve an exact eligible external draft after completed review | One exact-bound ApprovalRecord is persisted idempotently |
| E6-18 | Reapprove the unchanged exact binding | Existing approval is returned; no duplicate authority/effect |
| E6-19 | Change version, route, language, draft, privacy result, policy binding, or supporting relation | Prior approval becomes stale and cannot authorize export |
| E6-20 | Browser/model sends `approved=true` without Runtime record | Denied; client/model state grants no permission |
| E6-21 | Restart after matrix, finding resolution, wait, approval, or invalidation | Repository truth is restored and every binding is revalidated |
| E6-22 | Inject persistence failure during a mutation | Prior valid state remains authoritative; safe error/retry and audit are visible |
| E6-23 | Inspect graph state and Trace | Only allowlisted IDs/hashes/sanitized outcomes exist; no raw private payload |
| E6-24 | Correct M1-M4 after approval | Knowledge Card, relation support, matrix, findings, draft, and approval invalidate in dependency order |

## 15. Test strategy

### 15.1 Isolated branch before E5 merge

- pure route-policy tests for five routes, four states, reason precedence, and
  supporting/missing references;
- privacy validator, resolution transition, hash, and failure tests;
- approval binding, stale-field matrix, idempotency, and client/model bypass
  tests using a stored fixture draft;
- topology/state/privacy contract tests using isolated graph fakes while the
  asynchronous Checkpoint 1 review is open; production graph wiring still
  waits for the checkpoint and the real E5 handoff;
- React component/view-model tests with sanitized mocks;
- fixture builders and expected behavior for the four public categories;
- no migration, live predecessor, device, or milestone-completion claim.

### 15.2 Formal integration after E5 merge

- real E5 composed view and relation-permission handoff;
- real SQLite repositories, restart, migration upgrade/rebuild, and stale
  invalidation;
- production startup-compiled LangGraph and one resume authority;
- public HTTP seam plus generated frontend contracts;
- live React route/privacy/approval flow;
- correction and `GENERALIZE`/`REMOVE` canonical-version behavior;
- one explicit deny/failure/recovery terminal;
- complete affected backend/frontend/QA regression.

### 15.3 W7900/local-model evidence

If production E6 uses a local-model privacy/claim proposal, the stable review
head must run at least one privacy-risk structured proposal and one invalid or
abstaining case through the approved W7900/ROCm/vLLM path. Runtime validation,
permission denial, persisted outcome, failure, model identity, configuration,
timing, call count, and terminal state are recorded. If E6 remains entirely
deterministic after consuming E5 output, it makes no new E6 model-quality claim;
the combined E5-E7 and E8 evidence still proves the complete local Agent path.

## 16. Evidence packet

The stable E6 packet uses the repository evidence contract and records:

- exact implementation commit, branch, dirty-state result, workflow/topology,
  schema/migration, policy, model/runtime, and fixture identities;
- route matrix for complete and route-ineligible fixtures;
- privacy findings/actions UI and API evidence;
- approval success, denial, idempotency, and stale-invalidation evidence;
- correction dependency-invalidation Trace;
- restart and one failure/recovery result;
- relevant commands, exit statuses, public check summaries, retained failures,
  unverified areas, and rollback;
- W7900 evidence only when a real E6 local-model claim is made.

Sanitized Git packet target:

```text
evidence/milestones/e6-m5/<run_id>/
  manifest.json
  summary.md
  artifacts/
```

Raw/private/large material remains under:

```text
/workspace/amd-track2-agent/evidence/e6-m5/<run_id>/raw/
```

No raw source text, prompts, responses, credentials, model weights, private
fixtures, hidden QA, gold answers, or exact private thresholds enter Git.

## 17. Parallel delivery and file ownership

Before E5 merges, E6 may change only newly owned isolated M5/policy/UI feature
modules, tests, mocks, fixture builders, and this specification. It must not
independently change:

- `app/experience_asset/domain/models.py` or shared enums;
- checked-in OpenAPI/JSON Schema/frontend generated types;
- migration numbers or shared repository implementation;
- API root/startup wiring or production workflow entry;
- `web/src/App.tsx` or shared route registration;
- E5 relation authority or E7 renderer/export implementation.

After E5 merges, the E6 owner synchronizes current `main`, replaces mocks with
the reviewed E5 handoff, performs the minimum synchronized contract/migration/
API/workflow/UI integration, reruns affected checks, and records independent E6
acceptance before merge. E7 then synchronizes E6 and completes the real
RouteDraft→approval→export journey.

## 18. Failure, security, privacy, and rollback

- Unknown/stale IDs, hashes, versions, relations, findings, routes, drafts, or
  approvals fail closed with safe user-visible reasons.
- Imported text and model output remain untrusted data and cannot alter policy,
  tool identity, approval, or graph routing.
- All private inference remains local and loopback-bound; no remote fallback is
  permitted for core behavior.
- Mutations use optimistic expected-version checks and idempotency keys; partial
  persistence failure retains the prior valid version and an auditable failure.
- Approval and finding logs contain identifiers, hashes, categories, safe
  outcomes, and timing—not raw private content.
- Rollback disables M5 shared-entry wiring and approval creation, restores the
  last accepted E5 workflow/version, retains immutable product/evidence
  history, and leaves isolated E6 modules/tests available for correction.

## 19. Checkpoint plan and unresolved approvals

### Checkpoint 1 — Contract / Schema + Fixture

Must explicitly confirm:

1. Section 2.1 symbol/field-shape interpretation;
2. Section 2.2 RouteDraft→Approval execution order;
3. five-route policy and reason-code vocabulary;
4. privacy detection layers and category/action policy;
5. M5 context composition and relation-support semantics;
6. approval sidecar/view authority and route-draft hash semantics;
7. LangGraph nodes/edges/state/workflow/topology/retry/terminal contract;
8. four public fixtures and E6-01 through E6-24;
9. files owned by the isolated E6 branch and the reviewer;
10. evidence packet and whether E6 makes a new local-model/W7900 claim.

No production graph, shared schema, migration, API root, or live E5 integration
begins before this asynchronous checkpoint passes. Work on isolated policy and
application modules, contract-equivalent mocks, fixtures, tests, and feature UI
may continue while that review is open, as authorized by PR #28.

### Checkpoint 2 — Runnable backend/UI vertical slice

- isolated E6 policy/privacy/approval and UI pass against frozen mocks;
- before this Draft PR exits isolated review or enters shared integration, the
  shared integration owner adds a required frontend CI job covering tests,
  lint/typecheck, and production build; until then frontend results are locally
  reproducible evidence, not an independently enforced GitHub check;
- after E5 merge, the same behavior passes through real SQLite, Runtime,
  startup-compiled graph, public HTTP, typed client, and React UI;
- at least one denial/failure/recovery reaches a real terminal;
- restart and dependency invalidation preserve no stale permission.

### Checkpoint 3 — Evidence / promotion

- all affected public checks and four fixture categories pass;
- exact-head evidence, failures, rollback, privacy/disclosure scan, and
  unverified areas are retained;
- required real W7900 evidence is complete or explicitly marked not claimed;
- no Critical/High correctness, privacy, permission, persistence, RAG, or
  contest risk remains;
- independent E6 acceptance is recorded before formal merge;
- combined E5→E6→E7 acceptance remains mandatory before functional freeze.

## 20. Definition of done

E6 is done only when:

- five complete and truthful route decisions are durable and visible;
- route reasons and supporting/missing evidence are inspectable;
- privacy findings and user actions obey the approved policy;
- content-changing actions create a new canonical version and invalidate
  dependants;
- approval is explicit, exact-bound, idempotent, restart-safe, and stale after
  every bound change;
- preview/download/model/browser state cannot grant external permission;
- M5 LangGraph orchestration uses one resume authority and bounded state;
- real E5 integration, API/UI behavior, failures, restart, and fixtures pass;
- evidence is reproducible, sanitized, exact-commit, and reviewable;
- the quality owner records independent E6 acceptance;
- no claim is made for E7 exports, combined acceptance, or E8 Baseline before
  those later gates actually pass.
