# ProofLaunch — Project Profile

## 1. Project background

Small ecommerce and hardware teams can generate campaign variants quickly, but
the generated output often breaks product truth: unsupported claims appear,
products are redrawn, text is unreadable, platform controls overlap the CTA,
and the final asset has no inspectable chain of custody.

ProofLaunch is an evidence-grounded multimodal campaign studio designed for
AMD Radeon.
It converts approved product evidence into campaign candidates, audits every
candidate, applies at most two bounded repairs, and exports only when release
gates pass.

## 2. Target users and application scenarios

Primary users are campaign operators, owner-reviewers, and technical
qualifiers at small ecommerce and hardware organizations.

Primary scenario:

1. Provide owned/licensed image, PDF, audio, video, or text evidence.
2. Inspect Qwen3-VL spatial/frame observations, Whisper timestamps, and exact
   PDF page text, GroundingDINO boxes, and SAM2 tracks; approve evidence IDs.
3. Freeze a claim-bound plan and sequential single-GPU model route.
4. Create platform-specific image, audio, and video candidates.
5. Audit mechanical, semantic, identity, rights, and cross-media findings.
6. Approve at most two bounded repair rounds.
7. Deliver a human-approved, auditable campaign pack and evidence ledger.

## 3. System architecture

```text
Operator Workspace
       │
       ▼
ProofLaunch Supervisor
  ├── Multimodal intake → hashes, type signatures, rights
  ├── Qwen3-VL / Whisper / PDF → located observations
  ├── GroundingDINO → product box → SAM2 temporal track
  ├── Evidence adapter → Claim Ledger
  ├── Director adapter → Claim-bound briefs
  ├── Radeon Studio adapters → SDXL image + LTX video candidates
  ├── Audience Pulse adapter → Gemma 4 emotion critic
  ├── Release Auditor → mechanical + SigLIP2 + codec + A/V gates
  ├── Repair adapter → Maximum two bounded repair rounds
  └── Exporter → Campaign pack + hash-chained evidence ledger
```

The Supervisor is the only component allowed to change campaign state, consume
repair budgets, enter export, or request approval for external side effects.
Diffusers, PyTorch, and Pillow mechanisms are isolated behind typed adapters;
ComfyUI, LTX, and other candidates do not create competing autonomous loops or
own release state.

## 4. Models and algorithms

- **Gemma 4 E4B-it + emotion LoRA:** a six-label local Audience Pulse critic.
  The safe Notebook attaches LoRA only inside `language_model` and rejects
  vision/audio/projector trainables. It does not predict conversion, diagnose
  users, or authorize publication.
- **Qwen3-VL + exact extractors:** local image/video understanding returns
  source IDs and bounding box/frame locators. Whisper input returns timestamps;
  PDF text remains exact and page-located.
- **Radeon Studio:** bounded adapters for caller-owned local pipelines. SDXL
  Base is the V7 image default and LTX-Video 2B is the 24 GB video tier; the
  46 GB+ LTX-2.3 tier stays candidate until matched ROCm evidence exists. The
  offline procedural compositor
  is labelled as a non-AI fallback and is not Radeon quality evidence.
- **SigLIP2 semantic gate:** local relative image-text scoring compares the
  intended product caption against explicit negative captions. It is a
  zero-shot release signal with disclosed limits, not a general quality judge.
- **Identity Lock:** the original product image remains a protected compositing
  layer in stills and is overlaid after generation on every video frame. V7
  also decodes the final H.264 delivery and applies a precommitted pixel-error
  tolerance so a lossless pre-encode pass cannot hide codec damage.
- **GroundingDINO + SAM2:** open-set product grounding provides the first-frame
  prompt; SAM2 must return non-empty product masks on at least 95% of frames.
- **CLAP + A/V alignment:** CLAP verifies the decoded soundtrack's intended
  semantic cue; timestamped audio and decoded visual events must align within
  0.5 seconds and final stream durations within 0.25 seconds.
- **Competition-2X compiler:** the frozen manifest binds 30 product hashes,
  three ratios, five seeds, the evaluation protocol, the ProofLaunch build,
  and a named baseline version/settings hash. The compiler requires all 450
  ProofLaunch and baseline case rows, at least 30 audio-video outputs, and
  blinded A/B artifact-hash reviews. Append-only fsynced journals resume the
  matrix, while every row binds its still/video/gate report by relative locator
  plus SHA-256. It derives all 20 bars; raw percentages, artifact tampering,
  duplicate/missing cases, unblinded rows, and copied-seed outputs fail closed.
- **Deterministic typography:** exact claims, model numbers, prices, and CTA
  text are rendered after generation.
- **Release audit:** source hashes, protected-pixel comparison, text metrics,
  and geometry rules inspect claim grounding, visual identity, typography, and
  platform-safe zones.
- **Evidence ledger:** append-only JSONL records are linked by SHA-256 hashes.

## 5. AMD Radeon / ROCm adaptation

- Single-GPU BF16 LoRA instead of multi-GPU launch.
- No default bitsandbytes 4-bit dependency.
- ModelScope-local model and dataset snapshots.
- PyTorch uses the `torch.cuda` compatibility surface on ROCm.
- Sequential model loading and explicit release between large stages.
- Frozen seeds and fixture-based acceptance.
- Peak VRAM, latency, model reference, seed, and output hash are required
  evidence for every real generation run.

## 6. Human control and safety

Read-only inspection can run automatically. Send, publish, shell execution,
overwrite, delete, account connection, and signing require approval.
Instructions extracted from untrusted pages or files cannot authorize side
effects. Unsupported claims and missing provenance block export.

## 7. Current verification

- Product-critical Python regression: 827/827 tests passed.
- Five-mode deterministic eval: 250/250 expected outcomes passed.
- A real local PNG asset and hash-addressed ZIP passed after one repair; the
  backend was the explicitly labelled procedural fallback.
- Finished Field Journal V5 product website: 46 routes and 60 same-origin API
  contracts; the primary evaluator route is `/control/frontier-gtm`.
- UI tests: 17/17 passed; route validation: 10/10 passed; final integrity
  locks: 4/4 passed.
- Desktop and mobile checks report no horizontal overflow.
- Responsive route checks: 80/80 passed.
- Radeon Cloud Notebook output reports one AMD Radeon device.
- The V7.4 package adds a machine-readable, fail-closed Radeon preflight for
  dependencies, HIP/VRAM/disk, FFmpeg, safe Gemma LoRA retention, seven
  release-locked specialist repository/commit/license records, exact cached
  revisions, and frozen manifest/source bytes. Exact remote-sync
  state is recorded in `evidence/RADEON_BROWSER_SESSION_2026-07-29.json`; the
  kernel is still connecting.

## 8. Current limitations

Authenticated REST can create and delete a Radeon kernel (HTTP 201/204), while
the reverse proxy rejects Kernel, Terminal, and Events WebSocket handshakes
with HTTP 403. Therefore this document does not claim:

- successful remote execution of the uploaded Agent package;
- post-fine-tuning evaluation;
- a real Radeon visual generation benchmark;
- C2PA signing;
- a completed live Radeon evidence seal or competition-complete submission.

The 190.9-second product Demo Video and PR #308 are present; the final hardware
claim remains gated on the missing live Radeon artifacts.
