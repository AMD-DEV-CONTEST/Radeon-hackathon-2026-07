# PROJECT

## Project Identity

- Name: Personal Experience Asset Agent (working title; final product name open)
- Repository: `kinnyuww/amd-devmaster-track2-agent`
- Primary users: Individuals who want to turn first-person experience into reusable private knowledge and audience-specific publishable artifacts
- Current lifecycle stage: Approved P0/L3; PR #7, PR #8, PR #12 and PR #13 are
  accepted and merged, with the execution plan at `main@b053f66`. The
  exact-current-commit W7900 rerun was accepted and T06 is `PASS`; E2/M1 awaits
  its bounded Issue

## Long-term Goal

Turn a person's tacit knowledge into reusable, evidence-aware assets. The Agent
should help the user clarify an idea or lived experience over time, preserve the
result privately, connect it to related assets, and produce audience-appropriate
deliverables without inventing evidence or publishing without approval.

## Current Capabilities

- Reproducible Radeon Cloud W7900/ROCm development environment
- Persistent `/workspace` layout, SSH access, coding-agent tooling, and team Git workflow
- Verified private vLLM-compatible local inference path with a small smoke model
- Product requirements and L3 architecture for the Experience Asset path are
  approved. E1 foundations and the corrected combined gate are on `main`; the
  first useful M1 product slice is not implemented

## Stable Product Boundaries

### Allowed

- Private-by-default capture, clarification, structuring, retrieval, and export of user-provided experiences
- Local open-model inference on Radeon Cloud through ROCm
- Evidence-aware transformations that distinguish source facts, user judgments, and Agent inferences
- User-reviewed privacy redaction and audience routing

### Prohibited or human-approval-only

- External publication or sending content to another person without explicit user approval
- Executing model-proposed tools without runtime validation and policy checks
- Sending private experience data to shared or closed remote model APIs
- Production deployment
- Destructive data operations
- Permission expansion
- Irreversible migrations

## Architecture Snapshot

- Main components: Web UI, Agent application/runtime, private model server, persistence, export renderers, evaluation and audit
- Data stores: SQLite canonical product datastore and local retrieval indexes under persistent `/workspace`; durable source code in GitHub
- External services: GitHub for source history; optional authenticated Radeon Cloud Web UI tunnel only after explicit approval
- Deployment target: Radeon Cloud, single Radeon PRO W7900 48 GiB, ROCm
- Existing architecture documents: `docs/DEVELOPMENT_ENVIRONMENT.md`, `docs/TEAM_GIT_WORKFLOW.md`, `AGENTS.md`

## Stable Constraints

- Budget: One contest GPU per approved account; avoid unnecessary paid or remote model calls and use one canonical integration/benchmark profile
- Hosting: Radeon Cloud permits one active pod per account; individual teammate instances may be used when separately approved, while final evidence uses the designated canonical W7900 profile
- Privacy/security: Private by default; local core inference; no secrets or private data in Git
- Maintainability: Reproducible commands, separate Agent/vLLM environments, observable and testable workflows
- Team/skill constraints: Three-person team using short-lived branches and reviewed integration

## Quality Baseline

- Test commands: `pytest`
- Build commands: Accepted E1 repository and frontend commands documented on
  `main`
- Run commands: Accepted E1 local Agent/frontend and W7900 verification
  commands documented on `main`
- Lint/type-check commands: `ruff check .`; repository shell/Python syntax checks from `AGENTS.md`
- Observability: Versioned refinement milestones, Agent state, route decisions, privacy findings, model/tool traces, reproducible model/Agent/UX benchmark evidence

## Durable Decisions

| Decision | Choice | Reason | Date | Source |
|---|---|---|---|---|
| Core product value | Make tacit personal knowledge reusable | Captures the stable value beyond any one scenario | 2026-07-23 | User discovery conversation |
| First asset path | Experience Asset | Provides a complete, testable lived-event loop while leaving Idea and Method assets extensible | 2026-07-23 | User decision |
| Delivery model | One canonical asset with five conditional audience routes | Avoids five disconnected products and prevents fabricated outputs | 2026-07-23 | User decision |
| First fixture | Anonymous adaptation of a public office-chair trial/return case | Understandable, closed-loop, evidence-rich, and suitable for privacy and routing tests | 2026-07-23 | User approval |
| Publication boundary | Privacy review plus explicit final approval | Keeps the user in control of sensitive or public actions | 2026-07-23 | User decision |
| P0 experience center | Five visible, editable, resumable refinement milestones with a useful first artifact | Makes clarification and tacit-knowledge recovery the product value instead of hidden preprocessing | 2026-07-23 | User requirement update |
| Progress integrity | State-derived milestones and ranges only; no fabricated percentage or unsupported countdown | Preserves trust and makes progress testable | 2026-07-23 | User requirement update and HCI review |
| Performance evidence | Frozen manifests and separate model-server, Agent-task, and refinement-UX benchmarks | Makes ROCm optimization and contest claims reproducible | 2026-07-23 | User requirement update and Track 2 presentation |
| Quality governance | Public L1/L2 quality contract plus quality-owner-only blind evaluation | Prevents implementation drift without teaching teammate Agents the hidden scoring target | 2026-07-24 | User approval |
| Quality gate policy | Critical/High block; Medium is conditional with owner/deadline; Low enters Backlog | Makes milestone decisions predictable without reducing quality to one score | 2026-07-24 | User approval |
| Performance evolution | Stage/component optimization directions may change prospectively through a versioned evidence-backed proposal | Keeps the framework adaptable without allowing post-result target changes | 2026-07-24 | User clarification |
| P0 Agent architecture | One durable LangGraph orchestration Agent with scoped local RAG, structured tool proposals and deterministic Runtime policy | Designed to make all five Track 2 capabilities judge-visible after implementation and real evidence, without multi-Agent latency and state drift | 2026-07-24 | User risk-review authorization |
| Optimization evidence sequence | Freeze `S0` from the known-good E2 serving reference, screen eight factor-isolated BF16 W7900 serving profiles through separate fixed-token performance and natural-output quality lanes, confirm at most four factors, optionally combine one mechanically selected set of safe orthogonal gains, and advance at most three fully confirmed profiles; treat quantization as an optional separately time-boxed compatibility probe; freeze the complete Agent separately as `A0` and make the final product decision only on the frozen seven-fixture/13-flow end-to-end matrix | Starts ROCm/vLLM optimization before the full UI is finished, permits one causal factor-to-composite optimization step, follows current Radeon support evidence, and prevents service-only speed or an unbounded search/quantization detour from overriding product quality, safety, deadline or Agent completion | 2026-08-03 | User approved the two-layer baseline and requested best-practice/deadline hardening before Codex execution |
| E1 model/runtime identity | Exact Qwen2.5-14B ModelScope revision and file manifest plus immutable historical vLLM wheel URL/SHA; current-pod acceptance remains gated | Stops nightly/model drift without misrepresenting historical smoke evidence as a current 14B pass | 2026-07-24 | User risk-review authorization |
| E2-E8 execution model | One accountable milestone owner, bounded contributors, three engineering checkpoints, deep audits at E2/E4/E6/E7 and lightweight asynchronous gates at E3/E5 | Enables continuous adjacent-stage preparation while retaining risk-based independent review and avoiding user-online hard locks | 2026-07-28 | PR #13 accepted/merged; user-approved review-cadence amendment |
| Cross-asset RAG order | Finish the current Knowledge Card through M4 before summary-only candidate discovery; require user-confirmed relations before detailed historical retrieval | Prevents early history from anchoring, contaminating or rewriting the user's current experience while preserving judge-visible local RAG | 2026-07-24 | User clarification and execution approval |
| [Optional E9 public demo](E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md) | Temporary access-code sessions and a one-worker bounded WebUI-adapter queue; no business-layer or canonical-schema change | Protects a publicly reachable judge demo and makes W7900 overload visible without turning P0 into a multi-user product | 2026-08-03 | User-approved E9 requirement |

## Known Long-term Risks

- The product can collapse into generic summarization unless it preserves evidence, decisions, boundaries, and version history.
- Broad user and domain coverage may create shallow route outputs without domain-specific evaluation.
- Public-source fixtures carry copyright and privacy risk if copied rather than paraphrased and anonymized.
- A single 48 GiB GPU constrains model size, context, concurrency, and latency.
- An impressive visual export can conceal unsupported claims unless facts and inferences remain traceable.
- Early cross-asset retrieval can anchor the interview on past conclusions and
  contaminate the current experience unless the M4 readiness and confirmation
  gates are enforced in both Runtime policy and tests.
