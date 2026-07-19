# Scoring Evidence Matrix

Audited: 2026-07-19 (UTC+8)

This matrix maps Radeon Voice Skill Foundry to the Track 2 main rubric. It is a
judge navigation aid, not a claim of an awarded score.

## Judge Quick Path

1. Live product: `https://radeon-voice-skill-foundry.pages.dev/`
2. Main Demo V2:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Radeon evidence: `WEEKEND_W7900_EXPERIMENTS.md` and
   `WEEKEND_W7900_V10_SUMMARY.json`
5. Lifecycle evidence:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/CONTINUOUS_OPERATION_DEMO_V2.mp4`

## Main 100-Point Rubric

| Rubric item | Weight | Implemented feature | Exact evidence | Demo timestamp | Residual risk |
|---|---:|---|---|---|---|
| Positioning and creative scenario | 20 | Voice-seeded cold-start verification converts hidden expert intent into a governed Agent Skill before risky execution | Project Specification sections 1-3; generated `SKILL.md`, policy, fixtures, receipts, and proof ZIP | Main V2 00:00-00:32 | Synthetic SOP audio is disclosed as a reproducible fixture |
| Decomposition, tools, RAG, and memory | 20 | Local RAG, typed tool capabilities, multi-step planning, versioned memory, and permission/privacy controls | Project Specification sections 4-5; source modules; proof ZIP | Main V2 00:35-03:36 | Production connectors remain behind the same deterministic capability gate |
| Smooth multi-turn interaction | 20 | Voice upload/recording, source review, compile, policy inspection, verification, proof, save/reuse, revision, and revalidation | Public module UI; current `36/36` regression suite | Main V2 00:35-03:36; Lifecycle V2 02:20-04:19 | Public availability depends on the current W7900 tunnel origin |
| Core inference on Radeon | 20 | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run locally on W7900-class `gfx1100` with ROCm 7.2.1 | Live `/api/health`; `radeon-audio-proof-v8-2026-07-18.json`; main Demo V2 proof ZIP | Main V2 00:09-01:52 | Main Demo V2 is the authoritative real-inference video |
| Targeted inference optimization | 20 | vLLM eager/graph serving, native ASR batching, compact structured output, exact Verified Skill reuse, Quark INT4/INT8 acceptance study | `weekend-v10-summary.json`; `quantization-v11-summary.json`; optimization reports | Main V2 03:38-04:13 | Quark INT8 is capacity-positive but rejected for speed and safety-quality regression |

## Capability Requirement

| Required category | Implementation | Evidence |
|---|---|---|
| Local RAG | Local policy and SOP retrieval with visible evidence injection | Main V2 01:14-01:52; Project Specification 5.1 |
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
| Exact Verified Skill reuse | `2.18 ms`, measured `11,052x` | `optimization-w7900-2026-07-17.json` |
| Voice Evidence v0.3 clean sample | `pass / 100` | `weekend-v10-summary.json` |
| 120 ms burst loss | `review / 88` | `weekend-v10-summary.json` |
| 280 ms burst loss | `quarantine / 65` | `weekend-v10-summary.json` |
| Quark INT8 model-load VRAM | `7.67 -> 4.29 GiB`, `-44.07%` | `quantization-v11-summary.json` |
| Quark INT8 KV-cache capacity | `27,520 -> 51,856 tokens`, `+88.43%` | `quantization-v11-summary.json` |
| Quark INT8 C8 throughput | `160.61 vs 253.74 tok/s`, `-36.70%` | `quantization-v11-summary.json` |
| Quark INT8 C128 safety gate | `11/51`, production rejected | `quantization-v11-summary.json` |
| Quark INT4 W4A16 storage | `8.06 -> 2.68 GB`, loader incompatible | `QUARK_QUANTIZATION_W7900_V11.md` |

## Demo Evidence Boundary

- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4` records real Cloudflare-to-W7900
  ASR and Agent inference. Use it for Radeon execution, workflow completeness,
  and optimization narration.
- `CONTINUOUS_OPERATION_DEMO_V2.mp4` uses deterministic ASR/compiler fixtures
  while performing real process restarts and durable recovery. Use it for
  compatibility, invalidation, and parent-child proof lineage only.

## Integrity Anchors

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
