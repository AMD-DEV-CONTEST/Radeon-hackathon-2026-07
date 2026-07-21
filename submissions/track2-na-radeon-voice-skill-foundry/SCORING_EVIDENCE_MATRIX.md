# Scoring Evidence Matrix

Audited: 2026-07-21 (UTC+8)

This matrix maps Radeon Voice Skill Foundry to the Track 2 main rubric. It is a
judge navigation aid, not a claim of an awarded score.

## Judge Quick Path

1. Live product: `https://radeon-voice-skill-foundry.pages.dev/`
2. Final Demo V3:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Radeon evidence: `WEEKEND_W7900_EXPERIMENTS.md` and
   `WEEKEND_W7900_V10_SUMMARY.json`

## Base 100-Point Rubric

| Rubric item | Weight | Implemented feature | Exact evidence | Demo timestamp | Residual risk |
|---|---:|---|---|---|---|
| Positioning and creative scenario | 20 | Voice captures conditions, exceptions, and prohibited side effects that are absent from a UI trace | Project Specification sections 1-3; generated `SKILL.md`, policy, fixtures, and proof ZIP | Demo V3 00:00-00:29 | Synthetic SOP audio is disclosed as a reproducible fixture |
| Decomposition, tools, RAG, and memory | 20 | Deterministic local retrieval, typed tools, multi-step procedure generation, versioned memory, and explicit promotion lifecycle | Project Specification sections 4-5; public Memory module; proof ZIP | Demo V3 00:29-04:15 | Retrieval is token-overlap search, not embedding or vector search |
| Smooth multi-turn interaction | 20 | Six server-accepted actions, transcript review, verification, promotion review, ledger export, and exact reuse | Public Voice/Proof/Memory modules; current `63/63` suite; Demo V3 proof and ledger artifacts | Demo V3 00:29-04:15 | The workspace simulates external side effects |
| Core inference on Radeon | 20 | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run locally on W7900-class `gfx1100` with ROCm 7.2.1 | Live `/api/health`; `radeon-audio-proof-v8-2026-07-18.json`; Demo V3 and main Demo V2 proof ZIPs | Demo V3 00:29-01:53; Main V2 00:09-01:52 | Real model waiting time is preserved |
| Targeted inference optimization | 20 | Same-hardware vLLM serving A/B, native ASR batching, and compact structured output | `weekend-v10-summary.json`; `optimization-w7900-2026-07-17.json` | Main V2 03:38-04:13 | Three-run compact-output A/B; vLLM C8 is a concurrent serving result |

## Optional 20-Point Optimization Bonus

| Bonus area | Result | Decision | Evidence |
|---|---|---|---|
| Quark INT4 | Model storage `8.06 -> 2.68 GB`; installed vLLM loader rejected the signed INT4 weight scheme | No serving claim | `QUARK_QUANTIZATION_W7900_V11.md` |
| Quark INT8 | Model-load VRAM `7.67 -> 4.29 GiB`; KV-cache capacity `+88.43%` | Rejected: slower and failed semantic gate | `QUANTIZATION_V11_SUMMARY.json` |
| Adaptive precision | INT8 responses rejected; FP16 fallback restored `12/12` accepted outputs | Safety experiment, not latency optimization | `ADAPTIVE_PRECISION_V12_SUMMARY.json` |

## Capability Requirement

| Required category | Implementation | Evidence |
|---|---|---|
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents, with visible evidence | Main V2 01:14-01:52; Project Specification 5.1 |
| Tool invocation | Typed file, report, mail, calendar, and network capabilities | Main V2 01:54-02:28; generated policy |
| Multi-step planning | Voice/action evidence -> constraints -> skill -> fixtures -> proof | Main V2 00:35-02:56 |
| Local memory | Versioned Verified Skill Registry and exact reuse | Main V2 03:08-03:36 |
| Permission/privacy | deny/review/allow decisions, redaction, confirmation, receipts | Main V2 01:54-02:56 |

## Measured Radeon Evidence

| Measurement | Result | Source |
|---|---:|---|
| vLLM graph, concurrency 8 | `257.65 output tokens/s` | `weekend-v10-summary.json` |
| Serialized Transformers, concurrency 8 | `20.66 output tokens/s` | `weekend-v10-summary.json` |
| Serving uplift | `12.47x` | `weekend-v10-summary.json` |
| Native ASR batch 8 | `85.35x aggregate real-time` | `weekend-v10-summary.json` |
| Native ASR batching speedup | `6.659x` | `weekend-v10-summary.json` |
| Compact output token reduction | `29.42%` | `optimization-w7900-2026-07-17.json` |
| Compact output generation-latency reduction | `30.03%` | `optimization-w7900-2026-07-17.json` |
| Identical promoted-skill reuse | `2.18 ms`; avoids a repeat model call | `optimization-w7900-2026-07-17.json` |
| Voice Evidence v0.3 clean sample | `pass / 100` | `weekend-v10-summary.json` |
| 120 ms burst loss | `review / 88` | `weekend-v10-summary.json` |
| 280 ms burst loss | `quarantine / 65` | `weekend-v10-summary.json` |
| Quark INT8 model-load VRAM | `7.67 -> 4.29 GiB`, `-44.07%` | `quantization-v11-summary.json` |
| Quark INT8 KV-cache capacity | `27,520 -> 51,856 tokens`, `+88.43%` | `quantization-v11-summary.json` |
| Quark INT8 C8 throughput | `160.61 vs 253.74 tok/s`, `-36.70%` | `quantization-v11-summary.json` |
| Quark INT8 C128 safety gate | `11/51`, production rejected | `quantization-v11-summary.json` |
| Quark INT4 W4A16 storage | `8.06 -> 2.68 GB`, loader incompatible | `QUARK_QUANTIZATION_W7900_V11.md` |
| Schema-constrained INT8 | JSON `2/12`, semantic admission `0/12` | `adaptive-precision-v12-summary.json` |
| Adaptive FP16 fallback | final accepted `12/12` | `adaptive-precision-v12-summary.json` |
| Real adaptive Voice-to-Proof | fallback bound in proof, `mail.send = deny`, `7/7` | `adaptive-precision-v12-e2e.json` |
| Real action contract | six server-accepted commands, P2 excluded, email/calendar remain draft-only, browser action tampering ignored | current public Voice module, `server/demonstration-store.test.ts`, proof `action_contract.json` |
| Sandbox execution proof | six before/after state hashes, controlled outputs, five probes, zero external effects | current public Proof module, `server/sandbox.test.ts`, proof `sandbox_replay.json` |
| Skill governance lifecycle | proof-hash-checked promotion, supersede, reasoned revoke, verified rollback to a new version | current public Memory module, `server/storage.test.ts`, governance receipts |
| Promotion impact gate | permission/constraint/action/runtime diff, risk acknowledgement, stale review rejection | current public Memory module, `server/promotion-review.test.ts`, PROMOTE receipt review hash |
| Governance audit ledger | previous-hash chain, payload/entry hashes, receipt reconciliation, local modification/deletion detection, JSONL export | current public Memory module, `server/governance-ledger.test.ts`, `/api/governance/ledger.jsonl` |

## Demo Evidence Boundary

- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.mp4` records the final continuous public
  product path, including real W7900 inference, promotion, ledger export, and
  exact reuse.
- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4` is supplementary performance
  narration for the same public Radeon path.
- `CONTINUOUS_OPERATION_DEMO_V2.mp4` uses deterministic ASR/compiler fixtures
  while performing real process restarts and durable recovery. Use it for
  compatibility, invalidation, and parent-child proof lineage only.

## Interpretation Notes

- The detailed Rules and Conditions define 120 possible points: a base 100
  plus an optional 20-point optimization bonus. The Luma overview summarizes
  only the base 100.
- Exact reuse is an application fast path for an identical promoted skill. It
  is excluded from the core GPU inference-speed claim.
- Voice Evidence scores are internal deterministic quality-gate values, not
  external speech-recognition accuracy scores.
- Ledger hashes are not digital signatures and are not anchored to an external
  immutable service.

## Integrity Anchors

- Final Demo V3 MP4:
  `85d989a952561650195322c080a46543b93b3070c84e0f89021e59d451a4148e`
- Final Demo V3 SRT:
  `a0406750ee3c3081597d8ede9ff8eccc853958dda76e54a024d98a87cf21c1ce`
- Final Demo V3 proof ZIP:
  `7898d888112b113d53fce7ca2f9f46eecdaf318c79625af665fa908622f78cc2`
- Final Demo V3 ledger JSONL:
  `ca04585f5531fc42333f219153b7e3cbabfd3c629917cb4c621e6066ab95fcb3`
- Main Demo V2 MP4:
  `87fa6304819f01f5c5861d685a9f0c048d71e2e909ab4c9ab133428833125133`
- Main Demo V2 proof ZIP:
  `b9d81491e3292ce0190f6042aefbc3de19f9cf236fc6ef3c0dc9cf72b06c61c5`
- Continuous Demo V2 MP4:
  `98c8b56fbc92c80376fabc0b0386a9ed2ecb9b5c97c25ddefebd6c80d2a4b243`
- Continuous Demo V2 child proof:
  `f27b8298e64b588f12a200104c65d7ea3c42ff690c2d2067a62e261ddd3c4a36`
- Weekend v10 summary:
  `4871e76d1d0204c5d0179418132ed778f53b8adc6a230120d2974ff61be7158a`
