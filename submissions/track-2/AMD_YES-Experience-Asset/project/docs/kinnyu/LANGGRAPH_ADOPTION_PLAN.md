# LangGraph E3–E8 Evolution Plan

Status: `PROPOSED / DEDUPLICATED AFTER E2 INTEGRATION`

This document defines only the LangGraph responsibilities that remain after
the E2/M1 implementation merged through PR #16. It does not repeat current
project status, product acceptance criteria, Git workflow, milestone cadence,
competition rules, or the E2 implementation contract.

Use the existing authorities for those concerns:

- [`CURRENT_ITERATION.md`](CURRENT_ITERATION.md) for product scope and `AC-*`;
- [`L3_ENGINEERING_PLAN.md`](L3_ENGINEERING_PLAN.md) for architecture and work
  packages;
- [`E2_E8_PIPELINE_EXECUTION_PLAN.md`](E2_E8_PIPELINE_EXECUTION_PLAN.md) for
  ownership, sequencing and review cadence;
- [`E2_M1_WORKFLOW_CONFORMANCE_ADDENDUM.md`](E2_M1_WORKFLOW_CONFORMANCE_ADDENDUM.md)
  for the implemented E2 workflow contract;
- [`../team-alignment/AGENT_ARCHITECTURE.md`](../team-alignment/AGENT_ARCHITECTURE.md)
  for the complete Agent, RAG, Runtime and permission boundaries; and
- [`../../spec/EVIDENCE_RETENTION.md`](../../spec/EVIDENCE_RETENTION.md) for
  evidence maturity and storage.

If this plan conflicts with an authority above, the authority wins and the
conflict must be reported instead of silently reconciled.

## 1. Outcome and Track 2 relevance

Grow the production E2 graph only when a later milestone needs durable,
observable orchestration. Each extension must help demonstrate a real Track 2
capability such as multi-step planning, local retrieval, structured tool
proposals, deterministic Runtime permission, durable memory, recovery or
verification. Framework-shaped nodes that do not change observable behavior
are prohibited.

This plan changes no product behavior by itself and does not promote any
milestone.

## 2. Boundaries inherited from E2

Every later graph version preserves these E2 invariants:

- SQLite application repositories remain canonical business truth.
- The LangGraph checkpointer owns only the production orchestration cursor.
- Graph state contains typed identifiers, bounded cursor data and sanitized
  outcomes, never the canonical asset, source text, raw prompt/response or
  renderer output.
- The model proposes structured actions; deterministic Runtime Policy validates
  tool, arguments, scope, identity, permission and privacy before execution.
- Effects and terminalization are idempotent; resume revalidates workflow,
  topology, code, model/runtime identity and current asset version.
- Every reviewable run records workflow version, topology hash, selected edges,
  node attempts, checkpoint references and sanitized policy/effect/verification
  outcomes.
- `DurableFakeAgentLoop` remains a test/contract fixture and cannot return to a
  production route.

The accepted E2 topology is the starting point, not text to duplicate here.
See the conformance addendum and its machine-readable checkpoint contract.

## 3. Stage-by-stage evolution

| Stage | Graph responsibility | Deterministic owner outside the graph | Required new proof | Prohibited shortcut |
|---|---|---|---|---|
| E3 / M2 | Add the Critical Moment Map subgraph and orchestrate M1→M2 invalidation/recompute. | Timeline parsing, source conflicts and canonical M2 writes stay in domain/application services. | M1 correction invalidates affected M2 state; missing/conflicting time remains visible; restart resumes once. | Guessing dates or conflicts; integrating before E2 promotion; adding a second resume cursor. |
| E4 / M3 | Add bounded structured-output repair, node retry, retry exhaustion, re-plan and safe-stop around the Decision and Evidence Ledger. | Retry budgets, tool allowlists, arguments, permission and effect verification remain Runtime/application decisions. | Invalid output, deny, tool failure, exhaustion and recovery reach explicit terminals without duplicate effects. | Unbounded whole-run retry; allowing the model or graph to grant permission; hiding failure. |
| E5 / M4 | Add Knowledge Card readiness, summary-only relation discovery, confirmation/decline, no-match and confirmed-detail paths. | Readiness, retrieval phase and asset scope remain deterministic policy/application decisions. | Pre-readiness cross-asset denial, summary-only discovery, explicit confirmation before detail and current-asset non-contamination. | Searching history before readiness; reading detail before confirmation; silently importing historical facts. |
| E6 / M5 | Add route evaluation, privacy review, approval wait and stale-approval invalidation transitions. | Route eligibility, privacy resolution and version/hash-bound approval validity remain deterministic policy. | Ready/blocked/ineligible outcomes, visible risk decisions and invalidation after a canonical change. | Treating preview/download as approval; automatic publication; reusing stale approval. |
| E7 | Reuse existing orchestration only when a non-deterministic prerequisite genuinely needs it; add no graph nodes by default. | Preview, HTML/Markdown/JSON rendering, export commands, deletion and ordinary CRUD remain deterministic application services. | Same-version outputs, explicit approval boundary and deletion failure/retry evidence. | Adding framework-display nodes or moving deterministic delivery into the Agent. |
| E8 | Freeze the complete correctness-first graph for Baseline v1 and measure it. A later Candidate may introduce a prospectively declared workflow/configuration version only when its exact delta, quality floors and rollback are frozen before measurement. | Benchmark manifests, comparison rules and promotion remain quality-owner controlled. | Exact-commit W7900/ROCm evidence, all failures, repeated comparable runs, quality floors and known-good rollback. | Introducing LangGraph for the first time, rewriting Baseline history, changing undeclared variables or cherry-picking the best run. |

The milestone owner and merge order remain those in the accepted E2–E8
pipeline. This table does not create Issues or authorize N+2 work.

## 4. Minimum contract for an extension

Before implementation, the affected milestone freezes:

1. the user-visible outcome and affected `AC-*`, L1 and L2 gates;
2. added/removed nodes and conditional edges;
3. typed graph-state additions and explicit forbidden payloads;
4. workflow-version and topology-hash rules;
5. retry/effect/terminal budgets and idempotency keys;
6. invalidation, restart, stale-state and rollback behavior;
7. public fixtures, negative paths and required evidence.

An extension does not need a new abstraction merely because a future stage
might use it. Implement only the current stage plus the bounded adjacent-stage
preparation allowed by the accepted pipeline.

## 5. Acceptance evidence

For a graph-changing milestone, the smallest complete proof includes:

- topology tests for every new conditional branch;
- production wiring showing one startup-compiled runner rather than per-request
  compilation or a wrapper around an old loop;
- checkpoint round-trip, restart, stale/incompatible safe-stop and effect
  idempotency coverage;
- state/Trace privacy checks and exact workflow/topology identity;
- the affected API, persistence and browser journey;
- public fixture success plus at least one denial/failure/recovery path;
- exact-commit W7900 evidence when required by the milestone or a competition
  claim; and
- a sanitized evidence packet following `spec/EVIDENCE_RETENTION.md`.

Green CI or a framework import is not evidence of product completion. A
documentation-only change to this plan requires repository/document checks,
not a fabricated GPU packet.

## 6. Change control and rollback

A future implementation may refine node names, internal subgraph layout or a
component metric when the observable contract remains intact and the change is
prospectively recorded. It must return for architecture approval when it would:

- introduce a second canonical or resume authority;
- move deterministic permission/privacy decisions into the model or graph;
- persist raw private content in graph state or Trace;
- change a public API/schema or cross-asset RAG boundary;
- replace LangGraph or add a new service boundary; or
- weaken a Critical/High quality floor for performance.

Rollback is one milestone at a time to the last accepted workflow version and
known-good model/server profile. Failed evidence remains append-only; it is not
rewritten to make a Candidate appear successful.

## 7. Explicit non-goals

- Re-describing the E2 implementation or claiming E2 promotion.
- Copying milestone ownership, dates, current PR status or acceptance criteria.
- Moving business validation, Runtime Policy, rendering or persistence into
  LangGraph for consistency of appearance.
- Pre-creating detailed E3–E8 implementation prompts or Issues.
- Publishing private QA, exact scoring thresholds, credentials or raw traces.
