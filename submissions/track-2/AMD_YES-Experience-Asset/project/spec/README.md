# Team Agent Specification Entry Point

> **Deadline-minimal Stage 2 override (2026-08-06):**
> [`STAGE2_MINIMAL_ONE_CASE.md`](../docs/kinnyu/STAGE2_MINIMAL_ONE_CASE.md)
> is owner-approved and supersedes all larger Stage 2 matrices, repetitions,
> bookends and time budgets. Reuse the accepted A0/S0 case, run the same case
> once on P1, retain the bounded comparison, then move directly to E9.

> **Final-sprint override (2026-08-05):** read
> [`FINAL_SPRINT_EXECUTION_PACKAGE.md`](FINAL_SPRINT_EXECUTION_PACKAGE.md)
> immediately after this page. It is owner-approved and supersedes older
> stage-by-stage approval, private-blind-suite, ownership, and execution-cadence
> instructions for the remaining E5–E9 work. Product, privacy, Runtime,
> local-inference, evidence, Git-safety, and competition requirements remain.

This directory is the stable starting point for every teammate and coding
Agent working on this repository. It is an index and execution protocol, not a
second copy of the product requirements.

> Before proposing architecture, changing files, or generating a task plan,
> read this page and the mandatory sources below. Then produce the alignment
> response required by [`AGENT_ALIGNMENT.md`](AGENT_ALIGNMENT.md).

## Authority map

Use the source that governs the question. Do not silently reconcile conflicts.

| Concern | Authoritative source |
|---|---|
| Deadline-minimal Stage 2 A0/S0 versus A1/P1 integration check | [`STAGE2_MINIMAL_ONE_CASE.md`](../docs/kinnyu/STAGE2_MINIMAL_ONE_CASE.md) |
| Final-day ownership, E5–E9 sequencing, disclosed validation matrix and no-wait review cadence | [`FINAL_SPRINT_EXECUTION_PACKAGE.md`](FINAL_SPRINT_EXECUTION_PACKAGE.md) |
| Current product outcome, P0 scope and `AC-*` | [`docs/kinnyu/CURRENT_ITERATION.md`](../docs/kinnyu/CURRENT_ITERATION.md) |
| Approved L3 architecture, ownership, dependencies and work packages | [`L3_ENGINEERING_PLAN.md`](../docs/kinnyu/L3_ENGINEERING_PLAN.md) |
| Track 2 rules, scoring, deadline, cloud facts and submission package | [`COMPETITION_AND_GROUP_SUMMARY.md`](../docs/COMPETITION_AND_GROUP_SUMMARY.md) |
| Durable product goal and boundaries | [`docs/kinnyu/PROJECT.md`](../docs/kinnyu/PROJECT.md) |
| Deferred ideas and future paths | [`docs/kinnyu/BACKLOG.md`](../docs/kinnyu/BACKLOG.md) |
| Repository, security, persistence and Git rules | [`AGENTS.md`](../AGENTS.md) |
| Proportional engineering route, review severity and Baseline/Candidate rules | [`DEVELOPMENT_STANDARD.md`](DEVELOPMENT_STANDARD.md) |
| Public business-quality gates | [`TEAM_QUALITY_CONTRACT.md`](../docs/team-alignment/TEAM_QUALITY_CONTRACT.md) |
| Executable public QA checks and fixtures | [`qa/README.md`](../qa/README.md) |
| Product explanation and approved discovery summary | [`AI_AGENT_DISCOVERY_PACKAGE.md`](../docs/team-alignment/AI_AGENT_DISCOVERY_PACKAGE.md) |
| Teammate-readable Agent graph, local RAG, tool and Track 2 capability mapping | [`AGENT_ARCHITECTURE.md`](../docs/team-alignment/AGENT_ARCHITECTURE.md) |
| Benchmark evidence and ROCm optimization method | [`BENCHMARK_PLAN.md`](../docs/team-alignment/BENCHMARK_PLAN.md) |
| Approved two-layer W7900 serving screen, strict score and implementation packages | [`SERVING_BENCHMARK_ENGINEERING_PLAN.md`](../docs/kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md) |
| Final local model service, P1 evidence boundary and S0 rollback | [`FINAL_MODEL_SERVICE_DECISION.md`](../docs/kinnyu/FINAL_MODEL_SERVICE_DECISION.md) |
| Master task status, registration, demo and submission readiness | [`COMPETITION_READINESS_CHECKLIST.md`](../docs/COMPETITION_READINESS_CHECKLIST.md) |
| Official requirement-to-plan coverage, completion expectation and gap audit | [`COMPETITION_REQUIREMENT_COVERAGE.md`](../docs/COMPETITION_REQUIREMENT_COVERAGE.md) |
| Milestone history, demo proof and evidence storage | [`EVIDENCE_RETENTION.md`](EVIDENCE_RETENTION.md) |
| Remote environment and team workflow | [`DEVELOPMENT_ENVIRONMENT.md`](../docs/DEVELOPMENT_ENVIRONMENT.md), [`TEAM_GIT_WORKFLOW.md`](../docs/TEAM_GIT_WORKFLOW.md) |

For product meaning, `CURRENT_ITERATION.md` takes precedence over `PROJECT.md`,
which takes precedence over `BACKLOG.md`. `AGENTS.md` independently governs how
work may be performed. The quality contract may add a stricter gate but cannot
weaken an approved acceptance criterion. Explanatory documents cannot override
any of those contracts. Report a conflict and stop before guessing.

## Core engineering preflight

Every change uses this short checklist. Read the full
[`DEVELOPMENT_STANDARD.md`](DEVELOPMENT_STANDARD.md) only when its routed area
is affected.

1. Classify the change as lightweight or material by actual impact.
2. State the outcome, non-goals, Track 2 relevance, and evidence impact.
3. Identify the authoritative contract and affected acceptance criteria.
4. Keep the branch and diff limited to the approved scope.
5. Add or update behavior tests when behavior changes.
6. Run the targeted checks and the repository-required checks.
7. Report unverified areas, secrets/private-data review, and rollback.

## Mandatory reading for every task

1. [`AGENTS.md`](../AGENTS.md)
2. [`FINAL_SPRINT_EXECUTION_PACKAGE.md`](FINAL_SPRINT_EXECUTION_PACKAGE.md)
3. [`docs/kinnyu/CURRENT_ITERATION.md`](../docs/kinnyu/CURRENT_ITERATION.md)
4. [`docs/kinnyu/PROJECT.md`](../docs/kinnyu/PROJECT.md)
5. [`docs/kinnyu/L3_ENGINEERING_PLAN.md`](../docs/kinnyu/L3_ENGINEERING_PLAN.md)
6. [`docs/COMPETITION_AND_GROUP_SUMMARY.md`](../docs/COMPETITION_AND_GROUP_SUMMARY.md)
7. [`docs/team-alignment/AI_AGENT_DISCOVERY_PACKAGE.md`](../docs/team-alignment/AI_AGENT_DISCOVERY_PACKAGE.md)
8. [`docs/team-alignment/TEAM_QUALITY_CONTRACT.md`](../docs/team-alignment/TEAM_QUALITY_CONTRACT.md)
9. [`qa/README.md`](../qa/README.md)
10. [`AGENT_ALIGNMENT.md`](AGENT_ALIGNMENT.md)
11. [`EVIDENCE_RETENTION.md`](EVIDENCE_RETENTION.md)

Read these additional sources when the task touches the named area:

| Task area | Additional source |
|---|---|
| Feature, architecture, dependency, contract, schema, permission, milestone, GPU, benchmark or performance change | [`DEVELOPMENT_STANDARD.md`](DEVELOPMENT_STANDARD.md) |
| vLLM, ROCm, model serving, latency, throughput, VRAM or concurrency | [`SERVING_BENCHMARK_ENGINEERING_PLAN.md`](../docs/kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md), [`BENCHMARK_PLAN.md`](../docs/team-alignment/BENCHMARK_PLAN.md) and [`DEVELOPMENT_ENVIRONMENT.md`](../docs/DEVELOPMENT_ENVIRONMENT.md) |
| Agent planning, RAG, tools, memory, permission or verifier behavior | [`AGENT_ARCHITECTURE.md`](../docs/team-alignment/AGENT_ARCHITECTURE.md) |
| Extending the production LangGraph after E2 | [`LANGGRAPH_ADOPTION_PLAN.md`](../docs/kinnyu/LANGGRAPH_ADOPTION_PLAN.md) |
| Branching, commits, pushes, handoff or shared Radeon Cloud use | [`TEAM_GIT_WORKFLOW.md`](../docs/TEAM_GIT_WORKFLOW.md) |
| Metric or optimization-direction adjustment | [`CHANGE_PROPOSAL_TEMPLATE.md`](CHANGE_PROPOSAL_TEMPLATE.md) |
| Public fixture, artifact conformance, or PR gate | [`qa/README.md`](../qa/README.md) and [`qa/expected/`](../qa/expected/) |
| Any implementation PR, milestone promotion, GPU run, Baseline/Candidate, demo or submission work | [`EVIDENCE_RETENTION.md`](EVIDENCE_RETENTION.md) |
| Issue creation, ownership, dependency or implementation sequencing | [`L3_ENGINEERING_PLAN.md`](../docs/kinnyu/L3_ENGINEERING_PLAN.md) |
| Contest claim, scoring strategy, demo, deadline or official submission | [`COMPETITION_AND_GROUP_SUMMARY.md`](../docs/COMPETITION_AND_GROUP_SUMMARY.md), [`COMPETITION_READINESS_CHECKLIST.md`](../docs/COMPETITION_READINESS_CHECKLIST.md), and [`EVIDENCE_RETENTION.md`](EVIDENCE_RETENTION.md) |
| Optional public WebUI, access code, session isolation, queueing, overload or demo tunnel | [`E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md`](../docs/kinnyu/E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md) and [`PUBLIC_DEMO_TUNNEL.md`](../docs/PUBLIC_DEMO_TUNNEL.md) |
| Future feature suggestion | [`BACKLOG.md`](../docs/kinnyu/BACKLOG.md) |

## Current contract snapshot

- Final sprint: owner-approved no-wait execution is active. Kali integrates
  E5–E7 and freezes/runs the E8 A0 Baseline; the owner finishes Stage 1 and
  later Stage 2; Ethan assembles E9 final deliverables in parallel. All known
  prior blind-evaluation intent is disclosed in
  `FINAL_SPRINT_EXECUTION_PACKAGE.md`; no executable private suite or Gold
  Answer exists and no private promotion step remains.

- Product: Experience Asset P0 — make implicit personal experience reusable.
- Requirement status: `APPROVED`.
- Product engineering status: L3 `APPROVED`; E1-A and E1-B were independently
  accepted through PR #7 and PR #8. PR #12 was then approved and merged at
  `main@cc5281af5a6b4ac2d8c2e593f7c8e7f014feb31d`, promoting the combined E1
  gate/T06 to `PASS`. PR #13 then merged the E2–E8 pipeline plan at
  `main@b053f66049e3747abef39d8380095a0128ed84b4`.
- E2–E8 execution proposal: the user approved
  [`E2_E8_PIPELINE_EXECUTION_PLAN.md`](../docs/kinnyu/E2_E8_PIPELINE_EXECUTION_PLAN.md).
  PR #13 is accepted and merged. The plan uses one owner per E2–E7 milestone,
  bounded preparation of only the
  immediately adjacent stage, strict sequential promotion and parallel E8
  evidence lanes. E2/E4/E6/E7 are combined deep-audit gates; E3/E5 are
  lightweight asynchronous technical gates.
- E1-A boundary: E1-A1 Contract, E1-A2 Durable fake loop and E1-A3 Real W7900
  gate are three independently reviewable checkpoints inside the one Issue #5 /
  PR #7, not three separate Issues.
- Integration status: the dependency order through PR #7, PR #8 and PR #12 is
  complete. The accepted exact-current-commit W7900/ROCm/14B packet is
  `evidence/milestones/e1-combined/20260727T055758Z/`; both earlier packets
  remain append-only.
- Active execution: Issue #15 freezes the three required E2/M1 checkpoints and
  is assigned to `Eas000n`; implementation is active on
  `codex/e2-m1-experience-brief`. See
  [`E2_M1_VERTICAL_SLICE.md`](../docs/E2_M1_VERTICAL_SLICE.md). Its first
  Contract / Schema + Fixture checkpoint is frozen and confirmed in
  [`E2_M1_CONTRACT_CHECKPOINT.md`](../docs/kinnyu/E2_M1_CONTRACT_CHECKPOINT.md)
  and the LangGraph vertical slice is in final integration. No E2 promotion or
  E3 integration is implied; E3 may perform only the accepted pipeline's
  bounded preparation until E2 promotion.
- Acceptance contract: `AC-01` through `AC-32`.
- Core inference: local open model on Radeon PRO W7900 through ROCm.
- Agent route: one bounded orchestration Agent with local RAG, structured tool
  proposals, deterministic Runtime permission, durable memory and verification.
- RAG order: M1-M4 may retrieve only current sources/same-asset versions;
  cross-asset candidate discovery starts only after `KnowledgeCardReady`, and
  detailed history requires explicit relation confirmation.
- Source of truth: GitHub for source; `/workspace` for persistent cloud working
  data, caches, environments and approved artifacts.
- Public quality contract: active; exact private scoring remains outside Git.
- Performance selection: approved two-layer funnel. `S0` screens 7–9 declared
  W7900 serving profiles and advances at most three hard-gate passers; `A0`
  later decides the product profile on the frozen complete Agent and business
  fixtures. Concurrency 1/2/4 are primary/secondary/diagnostic respectively.
- Evidence policy: every PR supplies enough outcome, risk, checks and rollback
  context for review. Milestone deep audits, GPU gates, performance work and
  submission claims preserve a full sanitized packet; raw/private/large
  evidence stays in its approved storage tier.

This snapshot is only a convenience. The linked authority files remain the
source of truth.

## Public/private quality boundary

For the remaining 2026-08-05 final sprint, the complete functional evaluation
matrix is public in `FINAL_SPRINT_EXECUTION_PACKAGE.md`. The older prohibition
below is retained only as a historical/sensitive-data safeguard: repository
review found no implemented hidden suite, private fixture, Gold Answer, secret
weight, or unpublished threshold, and none may block E5–E9. Secrets and genuine
private user data remain excluded from Git.

Team Agents may read and implement the public requirements, schemas, fixtures,
quality contract and benchmark method. They must not request, search for,
infer, create substitutes for, or commit:

- hidden test code or private fixture variants;
- private gold outputs, exact thresholds, weights or aggregation logic;
- `.qa-private/`, `private-qa/`, `benchmarks/private/`,
  `benchmarks/hidden/`, or `data/quality-owner-private/` contents.

Agents must optimize observable product behavior, not a guessed answer key.

Before opening a PR, run:

```bash
bash qa/gates/pr_gate.sh --mode contract
python3 -m unittest discover -s qa/tests -v
```

If the change emits a canonical Experience Asset, run artifact mode with the
real asset, public fixture ID, and progress event as documented in `qa/README.md`.

## What alignment does and does not authorize

Completing the alignment response authorizes discussion only. It does not
authorize implementation, infrastructure changes, public exposure, use of
private data, commits, pushes, merges, releases or destructive operations.
Those actions still follow `AGENTS.md`, the approved engineering route and the
user's current authorization.

## Maintaining this entry point

Keep one canonical copy of each decision. Update the authoritative document,
then update this index only when its location, status or reading route changes.
Do not paste detailed requirements into `spec/` merely for convenience.
