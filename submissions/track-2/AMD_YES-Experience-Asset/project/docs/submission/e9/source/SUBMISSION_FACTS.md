# Experience Asset - Submission Fact Source

- Status: `DOCUMENTATION_READY / DEMO_PENDING / PUBLICATION_PENDING`
- Competition: AMD AI DevMaster Hackathon 2026 - Track 2
- Current repository snapshot: `main@c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd`
- Tested application implementation: `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
- Material snapshot ID: `EA-SUBMISSION-E9-20260806-R8`
- Final submission language: English

This file is the working claim source for the PDF, PPT, Judge Entry, README,
Demo narration and official submission PR. It does not replace the immutable
engineering packets cited below.

## Official submission surface

The organizer requires four English material categories and one submission
action:

1. Project Specification covering the application scenario, Agent
   architecture, core capabilities, model/local deployment and Radeon
   inference optimization;
2. complete source code plus a README with environment setup, dependencies and
   startup instructions;
3. a recommended 3-5 minute Demo Video showing the actual application and its
   Radeon GPU execution;
4. one PPT or Poster; this project uses a seven-slide English PPT;
5. a fork of the organizer repository and an English submission PR titled
   `Track 2, AMD_YES, Experience Asset`.

Official source:
https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07

## Frozen product definition

> Experience Asset is a private local Agent that turns fragmented first-person
> experience into an evidence-bound, editable and reusable asset, then prepares
> audience-specific deliverables without surrendering user control over facts,
> privacy or approval.

The target user has a real experience, practice, professional insight or
product exploration worth preserving, but cannot easily separate source facts,
personal judgments, inference, uncertainty and reuse boundaries.

The product is not a generic writing assistant, social-media growth system,
automatic publisher, traffic predictor, professional-advice service or
multi-user collaboration platform.

## User-visible workflow

| Stage | Artifact | Question answered |
|---|---|---|
| M1 | Experience Brief | What happened, what is the source boundary, and what does the user want? |
| M2 | Critical Moment Map | Which cues and turning points changed the experience? |
| M3 | Decision and Evidence Ledger | What was decided, why, what action followed, and what evidence supports the result? |
| M4 | Insight and Boundary Map | What was learned, what is the counterfactual, and where does the lesson stop applying? |
| M5 | Route Readiness Matrix | Which audience routes are eligible, private and approved? |

The accepted path includes save/resume, correction-driven invalidation,
phase-gated relation discovery, privacy resolution, exact-bound approval,
preview and HTML/Markdown/JSON delivery.

## Architecture and authority

```text
React UI
  -> FastAPI
  -> LangGraph + deterministic Runtime
       planning / checkpoints / bounded transitions
       tool allowlist + argument validation
       phase-gated RAG + evidence identities
       privacy / approval / retry / terminal state
       SQLite versions + audit
  -> localhost OpenAI-compatible vLLM
  -> ROCm
  -> Radeon PRO W7900
```

The model proposes structured actions. It cannot grant tool permission,
authorize retrieval, approve disclosure, select a stale version or silently
rewrite the canonical asset.

## Grounding and retrieval boundary

Statements remain typed as source fact, user judgment, Agent inference or
unresolved information. The route-draft path validates referenced statement
identities and route eligibility; final editable wording still requires user
or editor review.

```text
M1-M4: current source + prior versions of this asset only
-> M4 Knowledge Card reaches explicit readiness
-> summary-only cross-asset candidate discovery
-> user confirms one relation
-> detailed retrieval from that relation only
```

No match, declined relation, permission denial, stale approval and safe failure
are valid visible outcomes. The project claims hallucination control and
evidence discipline, not hallucination elimination.

## Accepted claims

| Claim | Evidence status | Exact boundary |
|---|---|---|
| Integrated M1-M5 product and private delivery path | `PASS` at PR #52, implementation `c9ec074` | M1-M4 live browser journey plus real M5 route/private delivery observation on W7900; not a statistical benchmark |
| Complete local inference stack | `PASS` | Local Qwen3.5-9B BF16, vLLM 0.26.0, ROCm/HIP 7.2, Radeon PRO W7900; services remained loopback-bound |
| Integrated regression surface | `PASS` | 34 repository QA tests; backend pytest and Ruff; frontend lint/type/build, 18 contract checks, 223 tests and 16 non-live browser tests |
| Stage 1 serving optimization | `W7900_VERIFIED / SERVICE_ONLY` in stacked PR #39/#44 | P1 vs S0: p95 TTFT 83.89% lower, median E2EL 4.33% lower, output TPS 0.47% higher; P1 reliability 85% |
| 20K service usability | `W7900_VERIFIED / SERVICE_ONLY` in PR #44 | S0/P1/P4/P3 passed the bounded usability interpretation; retained semantic advisories; no new ranking |
| Minimal Stage 2 integrated comparison | `PASS` in PR #57 | Same Agent/model/case: S0 about 2.0 min, P1 109.21 s; one observation only, 0.0% cache hit, no causal or statistical speed claim |
| Final launch Profile | `P1-prefix-cache SELECTED / MERGED` in PR #58 | P1 passed the integrated safety check; `bash scripts/serve_final_vllm.sh` launches it and S0 is the one-command rollback |
| Seven-slide PPT and four-minute video structure | `PLAN_READY` in PR #55 | The video must center on real Web UI operation; slides do not substitute for the product Demo |

## Frozen identities

- Application implementation: `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
- Product evidence packet:
  `evidence/milestones/e8-a0-w7900/20260806T122806Z/`
- Stage 2 evidence packet:
  `evidence/performance/stage2-minimal/20260806T124938Z/`
- Model: `Qwen/Qwen3.5-9B`
- Model revision:
  `460979c3d11864dd16408d860ac930a360a2fac2`
- Precision: BF16; quantization: none; bounded structured requests disable
  thinking
- Device: Radeon PRO W7900, `gfx1100`, 96 CUs, 48 GiB VRAM
- Runtime: ROCm/HIP 7.2, vLLM 0.26.0
- Integrated profile: 20K context, GPU memory utilization 0.82,
  `max-num-seqs=2`, Qwen3 tool/reasoning parsers, localhost bind
- Candidate delta: `--enable-prefix-caching`
- Rollback: remove `--enable-prefix-caching`; no application or database
  migration is involved

## Claims that remain prohibited

- attributing the one-case Stage 2 timing difference to prefix caching;
- presenting the Stage 1 service ranking as complete-Agent acceleration;
- presenting the 20K overlay as a second ranking or complete-product quality
  guarantee;
- claiming that hallucination or privacy risk is eliminated;
- claiming statistical application latency, peak Stage 2 VRAM or cache benefit
  from the one Stage 2 journey;
- claiming that the Demo video, final public links or official submission PR
  already exist.

## Remaining publication actions

```text
FINAL_DEMO_VIDEO_URL
FINAL_OFFICIAL_PR_URL
```

All required document content is ready, and the registered team name is
`AMD_YES`. The tested application, W7900 evidence
and final launcher are frozen. The current PPT is valid as submitted; PR #59
may still improve the presentation-layer WebUI used in the recording, but is
not a document prerequisite and does not change the evidence claim unless it
changes the tested workflow. The team name is owner-supplied registration
metadata. The Demo and organizer PR URLs cannot exist before recording and
publication.

## What judges should understand in minutes

1. A reusable experience asset is different from one-shot generated prose.
2. M1-M5 makes ambiguity visible, editable, resumable and auditable.
3. LangGraph coordinates the workflow; deterministic policy owns authority.
4. Phase-gated RAG and exact-version approval prevent silent contamination and
   stale disclosure.
5. The complete local Agent ran on W7900, and its selected Profile has bounded,
   reproducible service and one-case integrated evidence.

## Stable terminology

Use these names in every artifact: Experience Asset, Experience Brief,
Critical Moment Map, Decision and Evidence Ledger, Insight and Boundary Map,
Route Readiness Matrix, canonical version, phase-gated RAG, exact-bound
approval, deterministic Runtime and P1-prefix-cache.
