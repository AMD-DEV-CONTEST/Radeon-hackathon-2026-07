# ProofLaunch

> Evidence-grounded multimodal campaign creation on AMD Radeon / ROCm.

**Team Banyan · AMD Track 1 · ProofLaunch: Multimodal GTM Studio**

## Judge quick route

| Start here | Purpose |
|---|---|
| [`JUDGE_START_HERE.md`](JUDGE_START_HERE.md) | Five-minute evaluator path and current blockers |
| [`web/index.html`](web/index.html) | Finished product website; start at `/control/frontier-gtm` |
| [`docs/COMPETITION_PACKAGE.md`](docs/COMPETITION_PACKAGE.md) | Canonical deliverable map |
| [`docs/ProofLaunch_Project_Profile.pdf`](docs/ProofLaunch_Project_Profile.pdf) | Required Project Profile |
| [`docs/ProofLaunch_Submission_Deck.pptx`](docs/ProofLaunch_Submission_Deck.pptx) | Supplementary English deck |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | Local, web, and Radeon setup |
| [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) | Model roles, limitations, and safety |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Evidence levels and claim boundaries |

Truth-bounded evaluator replay:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python demos/run_track1_demo.py
```

The replay verifies the governed workflow and hashes; it is not new Radeon
inference. See `SUBMISSION_GATE.json` for the live competition state.

## Apple Metal local-model runtime

All Apple-local Gemma/MLX scripts use the project environment and one pinned,
platform-conditioned base dependency set. Bootstrap or repair it without
downloading when the uv cache is already populated:

```bash
uv sync --extra social --offline
.venv/bin/python scripts/verify_apple_mlx_runtime.py
```

On Apple Silicon, an ordinary `uv sync` now preserves the MLX runtime; Linux
and Radeon hosts skip these platform-marked packages. The preflight fails
closed on a missing or mismatched `mlx`, `mlx-lm`,
`transformers`, or `huggingface-hub` version and separately verifies that the
current process can access Apple Metal. Do not borrow another project's virtual
environment; model snapshots remain external, immutable inputs selected by the
individual run command.

The operator can follow one tenant-scoped campaign from strategy through
production, approval, aggregate effect, unit economics, and promoted learning
in the [GTM Executive Cockpit](docs/product/GTM_EXECUTIVE_COCKPIT_V1.md).
The cockpit is available at `/control/gtm-cockpit` and verifies the server's
canonical SHA-256 before rendering; it never enables publish, send, spend,
automatic strategy mutation, 4A-effect, Top-1, or causal-revenue claims.
Human-promoted cross-device learning is context-arbitrated across industry,
B2B/B2C, lifecycle, budget, regulation, market, and selected channels. Paid
learning cannot enter zero-budget work, standard-risk learning cannot enter
high-regulation work, and conflicting channel directives fail closed for
named-human arbitration. A tenant-scoped, idempotent resolution is bound to the
exact frozen decision and may be frozen only by a later run; the source run is
never rewritten and the selected directive still requires explicit human
application.

**Competition:** AMD Radeon Hackathon 2026-07  
**Track:** Track 1 — Development of Multimodal Content Creation Tools  
**Submission language:** English  
**Team:** Banyan  
**Application:** ProofLaunch  
**Proposed PR title:** `Track 1, Banyan, ProofLaunch: Multimodal GTM Studio`

ProofLaunch turns company evidence, images, PDFs, audio/video references and
stage goals into an inspectable, human-governed GTM workspace and multimodal
campaign pack. Its frozen strategy matrix covers 20 industry archetypes across
B2B/B2C, pre-PMF/launch/growth/mature stages, zero/small/scaled budgets and
standard/high-regulation risk. This is verified contract coverage—not proof of
universal market effect—and every external publish, send or spend remains
disabled until a named human releases it.

## Product workflow

`Ingest → Understand → Evidence → Plan → Create → Audit → Repair → Human release`

One Supervisor owns campaign state, approvals, retry budgets, and evidence.
Models and external agents operate only through typed adapters:

- **Evidence:** source-bound claims with exact spans and approval state.
- **Understand:** local Qwen3-VL observations carry source IDs plus bounding
  box/frame locators; PDF text stays exact and page-located; optional Whisper
  input produces timestamped transcript evidence.
- **Plan:** campaign briefs reference approved Claim IDs.
- **Create:** SDXL image and LTX image-to-video generation are isolated behind
  local Radeon adapters; only one heavy model is resident at a time.
- **Audit:** four mechanical checks—claim, product identity, typography, and
  platform safe zones—plus SigLIP2, GroundingDINO→SAM2 temporal product
  tracking, CLAP audio semantics, decoded-MP4 identity, A/V timing, and
  cross-media evidence checks in the competition-2X tier.
- **Repair:** at most two bounded repair rounds.
- **Deliver:** fail-closed export plus a hash-chained evidence ledger.

## Current verified state

- Production runtime now creates real PNG assets with a deterministic offline
  fallback or a caller-owned local Diffusers pipeline; the fallback is never
  labelled as AI output.
- One cached Gemma 3 12B Apple-Metal load has now produced eight accepted
  zero-paid-media strategy cases spanning B2B/B2C, all four lifecycle stages,
  standard/high-regulation contexts and four primary-channel families. The
  separate anti-collapse audit records a balanced 2/2/2/2 channel distribution,
  eight unique strategies and maximum pairwise token-set Jaccard `0.23494`
  against a `0.60` ceiling. This remains mechanical local-inference evidence,
  not training, human preference, production effect, 4A quality, universal
  industry generalization or Radeon execution.
- The complete local suite contains more than **1,100 tests** and its latest
  full run completed successfully with one intentionally skipped bootstrap
  assertion. The release-critical subset separately records its exact Python
  and Node counts in
  [`evidence/v10/aug3-product-readiness.json`](evidence/v10/aug3-product-readiness.json).
  The earlier granular Python-only receipt remains available at
  [`evidence/v10/local-test-report.json`](evidence/v10/local-test-report.json);
  it is historical supporting evidence and is not presented as the current
  complete-suite result.
  The suite includes Workstream 24 single-port UI/API binding,
  media signature validation,
  immutable image/video product pixels, resumable task graphs,
  deterministic seed hashes, exact source spans, bounded repair, tamper
  detection, sequential local-model routing, multimodal-LoRA isolation,
  GroundingDINO/SAM2 adapter contracts, post-codec identity tolerance,
  audio-video event alignment, a fail-closed case-level 2X evidence compiler,
  append-only/fsynced matrix resume, still/video/gate-report artifact binding,
  blind candidate-hash validation, seed-copy detection, and verified ZIP
  export. The suite also attack-tests the Radeon preflight against absent HIP,
  low VRAM, wrong cached commits, license/revision drift, failed Gemma
  retention, post-freeze source tampering, exact 1,500-item program integrity,
  six-stage training rollback, 28 fail-closed V10 bars, the twelve
  breakthrough reference mechanisms, proxy-evidence rejection, and the exact
  10-researcher + 10-product-mechanism synthesis. The additional gateway tests
  prove official Token Factory priority, three-model failover, secret-free
  receipts, audited Fireworks fallback, quality-contract admission, and an
  absolute online-provider ban inside the competition core. Four additional
  contracts verify Gemma 4 exact-label scoring, text-projection-only LoRA,
  immutable vision/audio fingerprints, and DDP/FSDP2/RCCL launch safety.
  Eleven Adapter Stack tests additionally verify ten typed role templates,
  task/uncertainty/market/risk routing, a real PEFT in-place LoRA swap, bounded
  cache/rollback, no-merge control, quantization admission and single-card
  residency without claiming trained role weights.
- The evidence compiler closes **972/1,500** atomic TODOs as observed local
  deterministic mechanisms. The remaining **528** stay `not_started`;
  Token Factory teacher output, plans, and self-reviews cannot change those
  statuses.
- **250/250 synthetic control-plane eval cases passed** across five named
  failure modes (50 per mode); p95 on the latest recorded local run was
  27.587 ms.
- The V7 competition-2X Radeon path is sequential: Qwen3-VL →
  GroundingDINO → multimodal-safe Gemma 4 + LoRA → SDXL Base → SigLIP2 →
  LTX-Video 2B → SAM2 → CLAP. Optional audio/video input adds Whisper. Only
  one heavy model is resident at a time; the core path has no closed online
  API.
- Finished Field Journal V5 product website: **46 routes, 60 same-origin API
  contracts, 17/17 UI tests, 10/10 route validation, and 4/4 final integrity
  locks passed** in the current sealed readiness receipt. Desktop and mobile
  checks report no horizontal overflow.
- Responsive browser checks: **80/80 passed** at 320, 390, 1024, and 1440 CSS px.
- The V7.4 package adds a fail-closed `ProofLaunchRadeonPreflightV2` gate for
  dependencies, ROCm/HIP, ≥16 GB VRAM, ≥40 GB free disk, FFmpeg, local
  Gemma-safe-LoRA retention, and the complete frozen manifest/source-byte
  binding. Every external specialist is release-locked to a repository,
  40-character commit and license record; the preflight inventories the exact
  cached commits, not only repository names. The reviewer-readable lock is
  `config/model_supply_chain.json`. Remote deployment state and exact hashes
  are recorded separately in
  `evidence/RADEON_BROWSER_SESSION_2026-07-29.json`.
- The supplied Notebook records one AMD Radeon device and training through its
  training section.
- Browser upload verification placed the latest V10 gate at
  `src/fine-tune/models/gemma4/prooflaunch_cortex_x_v10_radeon_v6.ipynb`
  and the audited Gemma trainer at
  `src/fine-tune/models/gemma4/gemma4_emotion_lora_multimodal_safe_v3_4.ipynb`.
  The V10 remote metadata reports all 1,500 double-standard requirements.
  The local generated contract confirms 1,500/1,500 program-level official
  floors, 100 directly applicable submission-floor profiles, 1,500/1,500
  non-empty overdelivery gates, 1,500/1,500 required-facet profiles, and zero
  permission for proxy external evidence. The multi-GPU contract binds all
  1,500 TODOs to one supervisor/DAG and requires real DDP/FSDP2/RCCL,
  equivalence, and efficiency observations for the 1,100 compute-bearing
  TODOs; the remaining 400 are program-bound without fake GPU work. This is
  file-presence and local-contract evidence only, not a kernel-execution
  claim; see
  `evidence/RADEON_BROWSER_SYNC_2026-07-30.json`.
- The user-authoritative source order has been independently reconciled:
  the second attachment supplies `0001–1200`, the first attachment supplies
  `1201–1500`, and all 1,500 normalized requirement lines match the canonical
  program exactly with zero missing, duplicate, reordered, or changed items.
  This proves requirement integrity only and closes no implementation TODO;
  see
  `evidence/v10/source-reconciliation-300-plus-1200.json`.

## Current release blockers

This repository does not claim a completed competition submission yet:

1. Authenticated Radeon REST can create and delete a kernel (HTTP 201/204),
   but the platform currently rejects Kernel, Terminal, and Events WebSocket
   handshakes with HTTP 403. The uploaded packages therefore have not executed,
   including the new machine-readable preflight.
2. The authenticated template output currently reports
   `torch.cuda.device_count(): 1`. The 1,100 direct multi-GPU TODOs therefore
   remain `not_started`; a ≥2-GPU ROCm/RCCL environment is required before
   DDP/FSDP2, equivalence, speedup, or stability claims can pass. See
   `evidence/RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json`.
3. The multimodal-safe Gemma LoRA has not been retrained remotely; therefore
   its post-fine-tuning emotion and visual-retention gates are not recorded.
4. The local SDXL visual-generation adapter and SigLIP2 semantic gate have not
   passed their frozen Radeon fixture. The deterministic fallback is verified
   but does not count as generative-model evidence.
5. The frozen 30-product competition-2X benchmark, blinded human comparison,
   and Demo Video (official guidance recommends 3–5 minutes) have not been
   recorded.
6. The V10 rights-audited corpus, six Radeon training phases, frozen
   ablations, and independent 4A product/effect tests are absent. All twelve
   breakthrough bets therefore remain `HOLD`; none is presented as promoted.
See [`SUBMISSION_GATE.json`](SUBMISSION_GATE.json). A pull request must not be
opened while a P0 gate remains blocked.

## Quick start: local installation and reproduction

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python scripts/run_control_plane_eval.py \
  --cases-per-mode 50 \
  --output evidence/local/control-plane-eval.json
PYTHONPATH=src python scripts/run_reference_demo.py \
  --output evidence/local/reference-run \
  --unsafe-first-pass
```

The latest sealed full local-suite receipt runs 1,337 tests: 1,336 pass, zero
fail or error, and one bootstrap test remains an expected skip. The current
product-critical competition receipt separately records 827/827 passing tests.
The reference run
reaches `deliver` after one repair, and the campaign pack contains real PNG
assets plus a hash-addressed manifest and ZIP.

The reference result uses `prooflaunch/procedural-background-v1`; it proves the
multimodal compositor and release harness, not generative-image quality.

The current presentation challenger is
[`delivery-v6`](evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json).
It uses an “evidence becomes momentum” engine rather than a generic business
person and chart. Its source metadata records one Codex built-in cloud image
generation call with unreported provider model/accelerator and no controllable
seed; the 4K/portrait/1080p composition, voice/music mastering, captions and
film assembly are deterministic and content-addressed. It remains mechanically
ready but not human-preference, 4A-effect, Radeon, publication or revenue proof.

## Official-first development inference

External model and Agent calls use one audited gateway:

`AMD Radeon Token Factory → approved Fireworks fallback → fail closed`

The official route is fixed to
`https://developer.amd.com.cn/radeon/api/v1/chat/completions` and tries
Qwen3.6-35B-A3B, DeepSeek-V4-Flash, then MiniCPM5-1B. The fallback example
loads Kimi K2.6, GLM 5.1, DeepSeek V4 Pro, and gpt-oss-120b from Fireworks only
after the official models all return eligible availability/contract failures.
Authentication failures never trigger silent fallback.

Supply credentials through a secret manager or process environment only;
never add them to the request, config, receipt, Notebook, or repository:

```bash
prooflaunch-tokenfactory \
  --request ./private-request.json \
  --purpose "GTM teacher distillation" \
  --scope teacher_distillation \
  --fallback-config config/fireworks-fallback.example.json \
  --output ./private-result.json \
  --receipt ./tokenfactory-receipt.json
```

The full boundary is in
[`docs/ONLINE_INFERENCE_POLICY.md`](docs/ONLINE_INFERENCE_POLICY.md). The latest
redacted browser probe is
[`evidence/v10/tokenfactory-availability.json`](evidence/v10/tokenfactory-availability.json).
The all-1,500-task, anti-theatre quality contract is
[`docs/FRONTIER_1500_EXECUTION_PROTOCOL.md`](docs/FRONTIER_1500_EXECUTION_PROTOCOL.md).
The AMD Developer Program / Fireworks access state is
[`evidence/v10/fireworks-access-state.json`](evidence/v10/fireworks-access-state.json).
Online outputs may teach, critique, rank, repair, or distill the local system;
they do not count as local Radeon execution or competition benchmark evidence.
The official route is guarded at `$10/day`, `30` provider RPM, `24` client RPM,
4,096 output tokens per request, and a fresh usage snapshot before large
batches. KV cache counters are optional performance telemetry, not submission
eligibility criteria. Bulk teacher generation disables hidden Qwen thinking
and stores visible outputs only.

The dated frontier panel adds DeepSeek-V4-Flash-0731, MiniMax M3, and MiniMax
H3 without conflating their roles. V4/M3 enter the same-input Agentic GTM
successive-halving ladder; H3 enters the asynchronous 2K video lane. Direct
DeepSeek/MiniMax endpoints are correctly marked pay-as-you-go, while AMD's
daily sponsored quota is a separate access class. The 2026-08-02 OpenRouter
catalog exposes 18 exact `:free` variants among 455 models: twelve enter the
frozen chat comparison, while six speech/embedding/reranking/specialist
fallback variants stay behind modality-specific contracts. Groq Free Plan
adds GPT-OSS 120B/20B, Qwen3.6-27B and Compound. GitHub Models is excluded:
GitHub's current service notice says its playground, catalog, inference API and
BYOK were fully retired for every customer on 2026-07-30. NVIDIA NIM now also contributes the officially observed
free `google/diffusiongemma-26b-a4b-it` endpoint for text/image/video
understanding, alongside its existing long-context and Agent challengers.
Cerebras remains a payment-method-backed $5/30-day trial credit rather than a
standing zero-cost tier. Cloudflare contributes both GPT-OSS 120B and Gemma 4
26B within one shared 10,000-neuron daily allocation. The resulting 29-candidate
fixed qualification cohort fits inside a computed 47-call
successive-halving ceiling.
Only public or synthetic cases may enter these logged trial endpoints, and
their outputs remain evaluation-only pending model-specific output-rights
review. The current preflight finds no API credential environment variable, so
it records zero new live calls rather than fabricating a benchmark. See
[`config/cortex_x_v10_frontier_api_panel.json`](config/cortex_x_v10_frontier_api_panel.json)
and
[`evidence/v10/frontier-free-api-sprint.json`](evidence/v10/frontier-free-api-sprint.json).

The no-download local creative path now uses the installed, digest-pinned
`qwen2.5-coder:1.5b` as a bounded four-dimension creative-nucleus selector
instead of asking it to reproduce a mostly fixed 768-token candidate object.
The Harness compiles that 96-token maximum nucleus into the unchanged full
evidence, CTA, dual-channel and human-release contract. The observed V5 matrix
completed 8/8 B2B/B2C lifecycle-budget-risk cases, 24/24 localhost calls and
24/24 mechanically validated candidates with zero download and zero cloud
calls. This is local inference and deterministic compilation, not fine-tuning,
human preference, 4A effect or Radeon evidence. See
[`artifacts/local-gtm-creative-benchmark-v5/benchmark-receipt.json`](artifacts/local-gtm-creative-benchmark-v5/benchmark-receipt.json)
and
[`evidence/v10/local-gtm-creative-benchmark-status.json`](evidence/v10/local-gtm-creative-benchmark-status.json).
Those eight cases are also compiled into 48 identity-hidden candidate-versus-
baseline pairs and 240 empty five-human assignments. Portfolio promotion
requires complete reviews plus cross-segment wins; current human progress is
truthfully 0/240. See
[`artifacts/local-gtm-creative-benchmark-v5/portfolio-blind-review-v1/portfolio-blind-review-public.json`](artifacts/local-gtm-creative-benchmark-v5/portfolio-blind-review-v1/portfolio-blind-review-public.json).
The Training browser surface now runs the invitation-bound 240-task queue
through `/v1/portfolio-blind-review/*`, persists immutable reviews across
server restarts, and suppresses every recommendation until the whole portfolio
is complete. It can switch to the focused 30-task campaign scope; neither scope
auto-publishes, and the portfolio scope cannot auto-select a winner.

The same Training surface now also exposes a dedicated campaign visual-system
scope. Five invited humans each compare the identity-hidden V5/V6 4K hero,
4:5 social, and 1080p landing trio using five frozen visual-effect dimensions
and a blocking-defect gate. Promotion requires all five reviews, at least 4/5
overall preference, zero blocking defects on the recommended candidate, and no
dimension loss. Current progress is 0/5; the runtime never auto-switches,
publishes, admits the pack to production, or converts the result into a 4A or
business-effect claim. See
[`docs/product/CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md`](docs/product/CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md).
The invitation-bound surface can also export one token-free offline ZIP per
reviewer and accept the returned digest-bound JSON, so independent reviewers do
not need network access to the local API. Five owner-only kits can be prepared
with `scripts/export_campaign_pack_offline_review_kits.py`; the generated secret
directory is excluded from every submission and Radeon archive.

The primary Evidence → Brief → Create flow now hands Stage 3 into the real
persisted Campaign World State and Agent worker instead of the earlier waiting
simulation. A bounded context-quality receipt now seals 24 observed local calls
at 2.80% median / 2.91% p95 context utilization and 24 frozen 60-message
state-preservation replays. The production HTTP boundary now also runs a
versioned prompt-injection, PII and secret guardrail; its content-free,
hash-chained telemetry retains only hashes and counters for 90 days. A frozen
250-case mechanical red-team currently has 100% attack recall, zero synthetic
false blocks and zero escapes, while deployed real-traffic performance remains
explicitly unobserved. The evidence-bound 12-point launch audit currently
records eight passes and four explicit gaps; see
[`evidence/v10/gtm-context-quality-v1.json`](evidence/v10/gtm-context-quality-v1.json)
and
[`evidence/v10/production-guardrail-eval-v1.json`](evidence/v10/production-guardrail-eval-v1.json)
and
[`docs/product/AGENTIC_PRODUCT_READINESS_AUDIT_V1.md`](docs/product/AGENTIC_PRODUCT_READINESS_AUDIT_V1.md).

The Radeon reproduction control plane is in
[`config/cortex_x_v10_radeon_reproduction_contract.json`](config/cortex_x_v10_radeon_reproduction_contract.json).
It enforces one-heavy-model residency, measured release ordering, CPU offload,
VAE tiling, attention slicing, four revision-safe content-addressed cache
layers, bounded OOM/kernel/download recovery, offline manifests, and a
checksum-first clean-instance script. Its mechanical receipt explicitly leaves
all live Radeon runtime, performance, clean-instance, and archive-reproduction
fields unobserved.

The Workstream 24 control plane now exposes a real loopback single-port server:
the existing product UI, idempotent `POST /v1/runs`, run status, ordered SSE,
named human approvals, approval-gated evidence Bundle, Model Cards and a
blinding/evidence-class-labeled evaluation leaderboard. Seven ephemeral HTTP
integration tests exercise the wire contract. The generated fixture remains
explicitly simulated and performs no publishing or remote-model action. See
[`docs/SINGLE_PORT_SUBMISSION_API_V1.md`](docs/SINGLE_PORT_SUBMISSION_API_V1.md)
and
[`evidence/v10/submission-api-mechanical-fixture.json`](evidence/v10/submission-api-mechanical-fixture.json).

The product also exposes a pinned open-source social-collection registry and a
bounded, rights-aware `yt-dlp` executor for public or operator-authorized
sources. See
[`docs/OPEN_SOURCE_SOCIAL_COLLECTION_V1.md`](docs/OPEN_SOURCE_SOCIAL_COLLECTION_V1.md)
for the connector revisions, permission modes, hard access-control boundary and
raw-to-signal ingestion contract.
The deterministic plan proof is sealed at
[`evidence/v10/open-source-social-collection-mechanical-fixture.json`](evidence/v10/open-source-social-collection-mechanical-fixture.json).

The Aug 3 product walkthrough and its honest evidence boundary are documented
in [`docs/product/AUG3_DEMO_RUNBOOK.md`](docs/product/AUG3_DEMO_RUNBOOK.md). The
latest self-hashed product-critical regression receipt is
[`evidence/v10/aug3-product-readiness.json`](evidence/v10/aug3-product-readiness.json).

### North-American Top-10 4A research distillation

The date-pinned reference cohort now covers all ten agencies in the frozen
2026 North-America ranking. It contains 13 individually source-located seed
cases, including at least one complete 16-layer distillation for every agency
(13 complete cases total). Each complete record separates observed facts from
inference across business problem, audience job, tension, strategy, Big-Idea
mechanism, brand role, channel system, experience/tool mechanism, craft,
production constraints, measurement, reported outcomes, failure modes,
counterfactuals, transferable principles, and non-transferable specifics.
Campaign identity, copy, layouts, footage, audio, offers, and branded objects
are not stored as raw training assets.

The cohort manifest and audit are:

- [`config/north_america_4a_research_cohort_2026.json`](config/north_america_4a_research_cohort_2026.json)
- [`evidence/v10/four-a-campaign-research-audit.json`](evidence/v10/four-a-campaign-research-audit.json)

This is a real source-bound research layer, but not a fake 300-case corpus:
the 30-cases-per-agency / 300-total gate stays blocked until distinct
individual sources and all 16 layers are captured. Award recognition and
reported case outcomes are also kept separate from causal effectiveness.
Build and verify it with:

```bash
PYTHONPATH=src python scripts/build_four_a_campaign_research.py
python scripts/validate_four_a_transfer_corpus.py \
  --corpus-root data/tokenfactory_teacher_v10 \
  --output evidence/v10/four-a-transfer-corpus-validation.json
```

The official Token Factory overlay applies four additional passes to all 750
two-TODO batches: strategy distillation, creative/craft translation,
effectiveness red-team, and strict-JSON synthesis. The synthesis validator
allows only the thirteen source-bound case IDs, preserves a
`research_reference` partition, rejects unbound case names, and cannot mark
training, Radeon execution, human preference, business effect, or TODO closure.

## Local Radeon generation adapter

The core submission does not depend on a closed online API. A caller-owned
Diffusers pipeline runs the key visual inference locally:

```python
from diffusers import AutoPipelineForText2Image
import torch

from prooflaunch_remix.studio import DiffusersBackgroundProvider

pipe = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    revision="462165984030d82259a11f4367a4eed129e94a7b",
    torch_dtype=torch.float16,
).to("cuda")  # ROCm exposes the Radeon device through torch.cuda

background = DiffusersBackgroundProvider(
    pipe,
    "stabilityai/stable-diffusion-xl-base-1.0",
    steps=20,
)
```

The model-generated background is never allowed to redraw the supplied
product: ProofLaunch composites an immutable product layer afterwards and
audits source/layer hashes plus opaque output pixels before export.

## Operator workspace

```bash
cd web
npm run build
npm run preview -- --port 4173
```

The workspace is intentionally local and does not pretend that an unavailable
GPU/model backend has run.

## Radeon Notebook bridge

Upload this repository or the versioned Radeon archive, open
[`notebooks/prooflaunch_cortex_x_v10_radeon.ipynb`](notebooks/prooflaunch_cortex_x_v10_radeon.ipynb),
and follow the cells in order after the Jupyter kernel is connected.

V10 preserves the proven V7 benchmark gate and adds an exact 1,500-item
evidence program, twelve falsifiable breakthrough contracts, a 28-bar quality
gate, and a six-stage multi-GPU-first curriculum. DDP is the default when a
replica fits per GPU; FSDP2 is the verified memory fallback. The current
one-GPU template remains a debugging baseline and cannot satisfy direct
multi-GPU evidence. The canonical source wording is in
[`docs/CORTEX_X_V10_1500_TODO.md`](docs/CORTEX_X_V10_1500_TODO.md); the
dependency order and truth boundary are in
[`docs/CORTEX_X_V10_EXECUTION_ORDER.md`](docs/CORTEX_X_V10_EXECUTION_ORDER.md).

Build and verify the machine-readable control artifacts with:

```bash
PYTHONPATH=src python scripts/build_v10_program.py \
  <v9-0001-1200.txt> <v10-1201-1500.txt>

PYTHONPATH=src python scripts/build_v10_training_plan.py

PYTHONPATH=src python scripts/build_top1_4a_training_gate.py

PYTHONPATH=src python scripts/build_v10_gtm_seed_corpus.py

PYTHONPATH=src python scripts/build_v10_trajectory_kd_corpus.py

PYTHONPATH=src python scripts/build_v10_trajectory_kd_runtime.py

PYTHONPATH=src python scripts/build_v10_brand_memory_seed.py

PYTHONPATH=src python scripts/build_v10_brand_memory_runtime.py

PYTHONPATH=src python scripts/build_v10_supply_chain.py

PYTHONPATH=src python scripts/build_v10_curated_corpus.py

PYTHONPATH=src python scripts/build_v10_curriculum_evaluation.py

PYTHONPATH=src python scripts/build_v10_full_scenario_kernel.py

PYTHONPATH=src python scripts/build_v10_adapter_stack_contract.py

PYTHONPATH=src python scripts/build_v10_gtm_employee_contract.py

PYTHONPATH=src python scripts/build_v10_image_mastering_fixture.py

PYTHONPATH=src python scripts/build_v10_video_mastering_fixture.py

PYTHONPATH=src python scripts/build_v10_scientific_evaluation.py

PYTHONPATH=src python scripts/build_v10_safety_case.py

PYTHONPATH=src python scripts/build_v10_frontier_api_panel.py

PYTHONPATH=src python scripts/build_v10_radeon_reproduction.py

PYTHONPATH=src uv run --no-project --with 'torch>=2.2' \
  --with 'peft>=0.14' --with 'transformers>=4.45' \
  python scripts/run_peft_hotswap_probe.py

PYTHONPATH=src python scripts/run_v10_local_suite.py

PYTHONPATH=src python scripts/build_v10_breakthrough_matrix.py

PYTHONPATH=src python scripts/audit_v10_source_reconciliation.py

PYTHONPATH=src python scripts/apply_v10_todo_evidence.py
```

The base program builder starts with all 1,500 items open. The verified closure
step currently closes exactly **972** local mechanism items and leaves **528**
open; the allowlist and evidence pointers are recorded in
[`evidence/v10/todo-closure-report.json`](evidence/v10/todo-closure-report.json).
An item closes only after every declared D/A/I/E and T/P/X evidence pointer has
a locator, SHA-256, evidence class, and conclusion. Failed research can close
with a negative result, but it cannot enter the product path.

The AgentOmnia-inspired full-scenario control plane is recorded in
[`config/cortex_x_v10_full_scenario_gtm_kernel.json`](config/cortex_x_v10_full_scenario_gtm_kernel.json).
It unifies ten capabilities, eight atomic difficulties, four reasoning routes,
RCRL admission, failure-driven curriculum, PRD evolution, and eight non-ranked
ten-product frontier comparison sets. The associated
[`evidence/v10/full-scenario-training-audit.json`](evidence/v10/full-scenario-training-audit.json)
now binds a project-owned mechanical seed of 32 partition-isolated executable
environments, 152 tasks, 152 replay-verified visible trajectories, and 440
steps. A matched trajectory-KD layer adds 456 outcome trajectories, 1,824
role-local Planner/Worker/Critic/Supervisor trajectories, 192 visible
stop/retry/fallback/escalation policy examples, and 1,640 step-reward labels.
The frozen runtime adds 456 four-role hierarchical-credit records; immutable
short/medium/long stages containing 936/104/208 training-partition role traces;
controlled KL, compounding-error, tool-noise, and loop diagnostics; two
information-loss ablations; and a 72-outcome held-out mechanical evaluation.
Training promotion remains blocked because this is metadata-oriented
synthetic seed data rather than a scaled multimodal 4A corpus, and no trained
checkpoint, real online-RL/RCRL run, Radeon key inference, or multi-GPU receipt
has been observed. See
[`data/v10_gtm_seed/manifest.json`](data/v10_gtm_seed/manifest.json) and
[`evidence/v10/gtm-seed-corpus-audit.json`](evidence/v10/gtm-seed-corpus-audit.json),
plus [`data/v10_trajectory_kd/manifest.json`](data/v10_trajectory_kd/manifest.json)
and [`evidence/v10/trajectory-kd-seed-audit.json`](evidence/v10/trajectory-kd-seed-audit.json).
The runtime receipt and frozen card are
[`evidence/v10/trajectory-kd-runtime-audit.json`](evidence/v10/trajectory-kd-runtime-audit.json)
and [`evidence/v10/trajectory-card.json`](evidence/v10/trajectory-card.json).

Brand Genome Memory V1 adds a source-bound `MemoryAtom`, four memory kinds,
all seven product/brand/audience/Claim/channel/asset/creative-concept entities,
five typed evidence/conflict/supersede/applies-to/prohibited edges, and eight
explicit memory-policy decisions. Its bounded seed contains 13 atoms, five
edges, 16 balanced project-owned policy examples and a verified 17-event hash
chain. Conflicts are approval-arbitrated, updates preserve source revisions,
privacy uses role ACLs, context selection combines utility and token cost, and
arbitrary event rollback restores graph state. Entity, symbolic, injected-dense
and frozen hybrid retrieval run on a 12-case memory-only benchmark plus a
streaming benchmark. On these controlled fixtures only, hybrid precision is
1.0, stale recall is 0, mean context saving is 0.667, cross-Campaign transfer
is 1.0 and brand contamination is 0; vector-only and no-memory ablations are
inferior. Dense vectors are handcrafted fixtures, so learned retrieval quality
remains unclaimed. See
[`docs/BRAND_GENOME_MEMORY_V1.md`](docs/BRAND_GENOME_MEMORY_V1.md),
[`data/v10_brand_memory/manifest.json`](data/v10_brand_memory/manifest.json),
and [`evidence/v10/brand-memory-seed-audit.json`](evidence/v10/brand-memory-seed-audit.json).
The frozen runtime evidence is
[`evidence/v10/brand-memory-runtime-audit.json`](evidence/v10/brand-memory-runtime-audit.json)
and [`evidence/v10/memory-card.json`](evidence/v10/memory-card.json).

Supply Chain V3 adds a typed `LicensedSource`, disjoint allow/research/deny/review
policy, seven explicit-metadata license parsers, seven redacted risk scans,
research/commercial/competition profiles, append-only opt-out/deletion events,
five BOMs, exact offline snapshots, and revision/hash/rights hard gates. Its
fixtures contain only ProofLaunch-owned metadata and prove mechanics rather
than rights to external content. See
[`docs/SUPPLY_CHAIN_V3.md`](docs/SUPPLY_CHAIN_V3.md) and
[`evidence/v10/supply-chain-v3-audit.json`](evidence/v10/supply-chain-v3-audit.json).

Curated Corpus V2 mechanics define twelve corpus taxa, seventeen grounded GTM
artifact types, multimodal cleanup/dedup/alignment, five sample-quality axes,
reference-guided super-batches, concentration and balance constraints, entity-
safe/time-safe splits, and benchmark/prompt leakage scans. The runtime seed is
only twelve project-owned synthetic metadata records and explicitly records
zero training tokens and zero human reviews, so the scaled Agency/Curated
Corpus V2 gates remain open. See
[`docs/CURATED_CORPUS_V2_MECHANICS.md`](docs/CURATED_CORPUS_V2_MECHANICS.md) and
[`evidence/v10/curated-corpus-v2-mechanical-audit.json`](evidence/v10/curated-corpus-v2-mechanical-audit.json).

Curriculum Engine V1 completes Workstream 12's mechanical contracts with
blinded multi-principal Critic independence, matched failure-driven versus
static controls, and a content-addressed Evolution Report. Its 24 pairs are
controlled non-model fixtures and cannot support a training-uplift claim. See
[`docs/CURRICULUM_ENGINE_V1.md`](docs/CURRICULUM_ENGINE_V1.md) and
[`evidence/v10/curriculum-evolution-report.json`](evidence/v10/curriculum-evolution-report.json).

The resulting
[`evidence/v10/breakthrough-matrix.json`](evidence/v10/breakthrough-matrix.json)
contains one evidence bundle for each of BT25–BT36. It deliberately keeps all
twelve on `HOLD` until data rights, ablations, a successful Radeon trace,
independent 4A product testing, and frozen effect validation are observed.
The public-mechanism synthesis requested for ten research representatives and
ten AI product/technology representatives is recorded in
[`docs/V10_20_LENS_SYNTHESIS_2026-07-29.md`](docs/V10_20_LENS_SYNTHESIS_2026-07-29.md);
it is a set of falsifiable design lenses, not endorsement or invented
consensus.

The six training phases are deliberately sequential:
multimodal continued pretraining, curriculum SFT, direct feedback, on-policy
distillation, multi-objective RL, and sparse adapter consolidation. At most one
heavy model may be resident. Vision/audio towers and base weights remain
frozen; every stage must pass general multimodal retention and its
stage-specific gates or roll back.

The Adapter pseudo-MoE control plane is frozen in
[`config/cortex_x_v10_adapter_stack_contract.json`](config/cortex_x_v10_adapter_stack_contract.json)
and [`docs/ADAPTER_PSEUDO_MOE_EXECUTION_CONTRACT_V1.md`](docs/ADAPTER_PSEUDO_MOE_EXECUTION_CONTRACT_V1.md).
It verifies serving metadata, four-axis routing, actual PEFT LoRA hotswap
integration, bounded LRU caching, version/rollback, fail-closed no-merge and
quantization controls, and measured-memory single-card residency. The ten role
entries are untrained templates; all neural metrics and export/merge artifacts
remain null in the planned card.

The 4A GTM output contract in
[`config/cortex_x_v10_gtm_employee_contract.json`](config/cortex_x_v10_gtm_employee_contract.json)
adds claim-grounded cross-channel consistency without expression duplication,
pre-registered performance hypotheses, bounded A/B plans, fatigue detection and
sensitive-safe audience learning. It does not claim that TODO 0851–0889 skill
distillation or TODO 0896–0900 five-rater acceptance has run.

The 4K mastering contract in
[`config/cortex_x_v10_image_mastering_contract.json`](config/cortex_x_v10_image_mastering_contract.json)
and its [UHD fixture report](evidence/v10/image-mastering-fixture/report.json)
verify a real 3840×2160 project-owned composition: product/logo/text masks,
exact product-layer recomposition, content-addressed native-resolution type,
Google no-text and social-safe variants, five hard image rewards, and a
protected local-repair gate. All FLUX/SDXL/grounding/restoration executions and
all neural OCR/color/identity quality results remain explicitly open.

The content-addressed
[`config/cortex_x_v10_top1_4a_training_gate.json`](config/cortex_x_v10_top1_4a_training_gate.json)
raises admission to a rights-audited, Top-1/4A production bar. It pins twelve
public upstream systems at immutable commits but distinguishes repository code
licenses from asset-level training rights: unresolved web/image mixtures are
method-only or evaluation-only. Promotion requires at least 50,000 approved
samples, complete provenance/license coverage, sealed-test contamination zero,
hard negatives, counterfactual and repair trajectories, 4K/video/audio/screen
coverage, expert agreement, ten strong baselines, and real multi-GPU evidence.
The North-American 4A reference cohort requires ten agencies selected from
date-pinned independent rankings, at least thirty campaigns and five channels
per agency, five independent raters, and raw pairwise counts. “Top-1” remains
forbidden until every agency clears its Wilson non-inferiority gate and the
pooled 95% lower bound exceeds 0.60. The current admission state is correctly
`blocked`: no rights-approved GTM corpus or real >=2-GPU Radeon run has yet
been sealed.

First run
[`notebooks/gemma4_emotion_lora_multimodal_safe_v3.ipynb`](notebooks/gemma4_emotion_lora_multimodal_safe_v3.ipynb).
It uses the official multimodal model class, positively allows only numbered
text-decoder attention/MLP projections, rejects every trainable
vision/audio/projector/embedding/head parameter, requires exact pre/post
vision/audio module fingerprints, compares checkpoints on validation, and
touches the locked test only after selection. The supplied original and V2
Notebooks remain preserved for audit.

For more than one Radeon GPU, first run
[`scripts/verify_rocm_multigpu.py`](scripts/verify_rocm_multigpu.py), then
launch [`scripts/train_gemma4_emotion_multigpu.py`](scripts/train_gemma4_emotion_multigpu.py)
with the matching profile under `configs/accelerate/`. DDP is the controlled
throughput path; FSDP2 is the state-sharded memory path. Training never uses
`device_map="auto"`. The full finding and acceptance gates are in
[`docs/GEMMA4_EMOTION_LORA_AUDIT_2026-07-30.md`](docs/GEMMA4_EMOTION_LORA_AUDIT_2026-07-30.md).

The Gemma adapter reuses the Notebook's existing `predict_emotion_ft` callable:

```python
from prooflaunch_remix.audience_pulse import GemmaAudiencePulse

audience_pulse = GemmaAudiencePulse(
    classifier=predict_emotion_ft,
    model_ref="google/gemma-4-E4B-it+emotion-lora:modelscope-single-radeon",
)
```

Only the six declared labels are accepted. Unexpected model output becomes
`invalid` with zero confidence and cannot silently pass.

## Multimodal mission CLI

The planning CLI hashes each input, validates its real file signature, checks
declared rights, freezes a bounded DAG, and emits a sequential Radeon plan:

```bash
prooflaunch-mission \
  --media product_identity:owned:./product.png \
  --media evidence_brief:owned:./brief.pdf \
  --deliverable social_image:9x16 \
  --deliverable short_video:3x2:4 \
  --available-vram-gb 24 \
  --quality-tier competition_2x \
  --output ./prooflaunch-mission
```

`mission-plan.json` is a plan and evidence contract, not a claim that a model
has run. The V7 Notebook remains the executable competition-2X control; the
Cortex-X V10 Notebook wraps it with the stronger program, training, and
certification gates.

The 2X tier does not turn a single successful fixture into a benchmark claim.
V7 freezes exactly 450 still cases (30 products × three ratios × five seeds),
requires at least 30 complete audio-video cases, and compares the same matrix
against a declared baseline. It requires at least five raters and 150 blind
candidate-hash comparisons, zero unsupported claims, 100% evidence locators
and pre-encode identity, ≥95% encoded identity, A/V alignment, cross-media,
completion and valid seed-diversity group rates, ≤2% crashes, no worse
completion than the baseline, and ≥60% publish preference whose Wilson 95%
lower bound clears 50%. Raw aggregate percentages are rejected.

Each ProofLaunch result is appended and `fsync`-sealed as soon as a case
finishes. The row binds a per-case gate report, the still artifact, and any
required video artifact by traversal-free relative locator plus SHA-256.
Reopening the journal resumes at the first missing manifest case. The compiler
re-hashes every bound file before deriving rates.

V7.4 executes the matrix in nine deterministic, model-resident phases:
prepare, Qwen3-VL understanding, GroundingDINO grounding, Gemma planning, SDXL
still generation, SigLIP2 still audit, LTX-Video generation, SAM2 video
tracking, and CLAP/post-codec video audit. A phase is released before the next
heavy model can load. Successful activities, primary outputs, and sidecars are
hash-bound in an atomic checkpoint and are not repeated on resume. Frozen
product bytes are revalidated on every resume. Only explicitly transient
failures receive at most two retries; schema, permission, input-hash, and
unknown failures fail closed.

```bash
PYTHONPATH=src python scripts/build_competition_2x_manifest.py \
  evidence/radeon/multimodal-v7/products.csv \
  --benchmark-id prooflaunch-radeon-final \
  --protocol-sha256 <sha256-of-protocol> \
  --prooflaunch-build-sha256 <sha256-of-v7-archive> \
  --baseline-name "<named baseline>" \
  --baseline-version "<exact version>" \
  --baseline-settings-sha256 <sha256-of-settings> \
  --baseline-source-locator "baseline-settings.json" \
  --output evidence/radeon/multimodal-v7/manifest.json

PYTHONPATH=src python scripts/run_competition_2x_matrix.py preflight \
  --settings config/radeon_matrix_adapter.json \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --strict-cache \
  --output evidence/radeon/multimodal-v7/radeon-preflight.json

PYTHONPATH=src python scripts/run_competition_2x_matrix.py run \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --run-dir evidence/radeon/multimodal-v7/competition-2x \
  --adapter prooflaunch_remix.radeon_matrix_adapter:create_adapter \
  --resume

PYTHONPATH=src python scripts/compile_competition_2x_evidence.py \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --results evidence/radeon/multimodal-v7/prooflaunch-results.jsonl \
  --baseline-results evidence/radeon/multimodal-v7/baseline-results.jsonl \
  --human-comparisons evidence/human/human-comparisons.csv \
  --evidence-output evidence/radeon/multimodal-v7/competition-2x-evidence.json \
  --report-output evidence/radeon/multimodal-v7/competition-2x-report.json
```

Preflight exits `0` only when every blocking requirement passes. A missing
exact Hugging Face commit is a warning while downloads are allowed, but
becomes a blocker with `--strict-cache` or `local_files_only=true`; a
repository cached at a different commit does not pass. Repository, revision,
or license drift from `config/model_supply_chain.json` is always blocking.
Omitting `--manifest` is also an explicit warning: it proves runtime
readiness, not submission readiness. The report never substitutes for
measured model outputs or the 20-bar compiler.

The bundled production adapter reads
`config/radeon_matrix_adapter.json`. Its default Gemma paths point to the model,
LoRA, and retention evidence produced beside the extracted project by the two
Radeon Notebooks. Override the settings file with
`PROOFLAUNCH_RADEON_ADAPTER_SETTINGS=/absolute/path/settings.json`.

The adapter factory declares a versioned settings hash,
`system_kind=prooflaunch`, and `uses_closed_online_api=false`. It implements
the typed `CompetitionBenchmarkAdapter` contract in
`prooflaunch_remix.benchmark_runner`; output paths are assigned by the runner
and cannot escape the evidence directory. For multiple GPUs or isolated
workers, give every process the same immutable manifest and distinct
`--shard-index` values, then merge only complete, disjoint shards:

```bash
PYTHONPATH=src python scripts/run_competition_2x_matrix.py merge \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --run-dir evidence/radeon/multimodal-v7/competition-2x \
  --shard-count <worker-count>
```

Inspect the durable run journal with:

```bash
PYTHONPATH=src python scripts/record_competition_2x_case.py pending \
  --kind prooflaunch \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --results evidence/radeon/multimodal-v7/prooflaunch-results.jsonl
```

## Required submission materials

- [`docs/ProofLaunch_Project_Profile.pdf`](docs/ProofLaunch_Project_Profile.pdf)
- Complete source code and this reproduction README
- A Demo Video (official guidance recommends 3–5 minutes); use
  [`docs/DEMO_VIDEO_SHOTLIST.md`](docs/DEMO_VIDEO_SHOTLIST.md)
- [`docs/ProofLaunch_Submission_Deck.pptx`](docs/ProofLaunch_Submission_Deck.pptx) — supplementary English deck
- [`docs/SUBMISSION_CHECKLIST.md`](docs/SUBMISSION_CHECKLIST.md)
- [`docs/TRACK1_2X_ACCEPTANCE_MATRIX.csv`](docs/TRACK1_2X_ACCEPTANCE_MATRIX.csv)
- [`docs/FIVE_DAY_DELIVERY_RUNBOOK.md`](docs/FIVE_DAY_DELIVERY_RUNBOOK.md)
- [`docs/COMPETITIVE_BENCHMARK_PROTOCOL.md`](docs/COMPETITIVE_BENCHMARK_PROTOCOL.md)
- [`docs/COMPETITION_2X_QUALITY_CONTRACT.md`](docs/COMPETITION_2X_QUALITY_CONTRACT.md)
- [`docs/PRODUCTION_READINESS_SCORECARD.md`](docs/PRODUCTION_READINESS_SCORECARD.md)

## Truth boundary

Passing local tests proves orchestration, policy, repair, and evidence
mechanics. It does not prove ROCm compatibility, model quality, persuasion,
legal compliance, provenance signing, or competition performance. Those claims
require the evidence listed in the submission gate.
