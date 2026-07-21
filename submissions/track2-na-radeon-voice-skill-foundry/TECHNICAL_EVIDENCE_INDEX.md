# Technical Evidence Index

Published: 2026-07-21 (UTC+8)

This index connects the implemented product capabilities, Radeon measurements,
verification artifacts, and documented evidence boundaries.

## Project Materials

1. Live product: `https://radeon-voice-skill-foundry.pages.dev/`
2. Final Demo V3:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Architecture: `ARCHITECTURE.png`
5. Poster: `POSTER.pdf`
6. Radeon evidence: `WEEKEND_W7900_EXPERIMENTS.md` and
   `WEEKEND_W7900_V10_SUMMARY.json`

## System Capability Map

| Capability | Implementation | Evidence | Demo timestamp | Boundary |
|---|---|---|---|---|
| Voice-seeded workflow capture | Voice records conditions, exceptions, and prohibited side effects that are absent from a UI trace | Project Specification sections 1-3; generated `SKILL.md`, policy, fixtures, and proof ZIP | Demo V3 00:00-00:29 | Synthetic SOP audio is disclosed as a reproducible fixture |
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents | Project Specification sections 4-5; public Memory module; proof ZIP | Demo V3 00:29-04:15 | Retrieval is token-overlap search, not embedding or vector search |
| Tool invocation and planning | Typed tools and six server-accepted actions compile into a multi-step procedure, constraints, permissions, and fixtures | Public Voice and Proof modules; generated policy; proof ZIP | Demo V3 00:29-02:48 | The workspace isolates external side effects |
| Verification and procedural memory | Deterministic replay, five fail-closed probes, versioned memory, promotion, ledger export, and exact reuse | Public Proof and Memory modules; current `63/63` suite; Demo V3 proof and ledger | Demo V3 02:48-04:15 | Reuse applies only to an identical promoted skill |
| Core inference on Radeon | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run on W7900-class `gfx1100` with ROCm 7.2.1 | Live `/api/health`; `RADEON_AUDIO_PROOF_V8.json`; Demo V3 proof ZIP | Demo V3 00:29-01:53 | Real model waiting time is preserved |
| Targeted inference optimization | Same-hardware vLLM serving A/B, native ASR batching, and compact structured output | `WEEKEND_W7900_V10_SUMMARY.json`; source benchmark JSON in the project repository | Main Demo V2 03:38-04:13 | Compact-output A/B uses three runs; vLLM C8 is a concurrent serving result |

## Track 2 Capability Coverage

| Capability | Implementation | Evidence |
|---|---|---|
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents, with visible selected evidence | Main V2 01:14-01:52; Project Specification 5.1 |
| Tool invocation | Typed file, report, mail, calendar, and network capabilities | Main V2 01:54-02:28; generated policy |
| Multi-step planning | Voice and action evidence compile into constraints, a skill, fixtures, and proof | Main V2 00:35-02:56 |
| Local memory | Versioned Verified Skill Registry and exact reuse | Main V2 03:08-03:36 |
| Permission and privacy controls | Allow, review, and deny decisions; redaction; confirmation; receipts | Main V2 01:54-02:56 |

## Measured Radeon Evidence

| Measurement | Result | Source |
|---|---:|---|
| vLLM graph, concurrency 8 | `257.65 output tokens/s` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Serialized Transformers, concurrency 8 | `20.66 output tokens/s` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Same-hardware serving ratio | `12.47x` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Native ASR batch 8 | `85.35x aggregate real-time` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Native ASR batching speedup | `6.659x` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Compact output token reduction | `29.42%` | source optimization benchmark JSON |
| Compact output generation-latency reduction | `30.03%` | source optimization benchmark JSON |
| Identical promoted-skill reuse | `2.18 ms`; avoids a repeat model call | source optimization benchmark JSON |
| Voice Evidence v0.3 clean sample | `pass / 100` | `WEEKEND_W7900_V10_SUMMARY.json` |
| 120 ms burst loss | `review / 88` | `WEEKEND_W7900_V10_SUMMARY.json` |
| 280 ms burst loss | `quarantine / 65` | `WEEKEND_W7900_V10_SUMMARY.json` |
| Quark INT8 model-load VRAM | `7.67 -> 4.29 GiB`, `-44.07%` | `QUANTIZATION_V11_SUMMARY.json` |
| Quark INT8 KV-cache capacity | `27,520 -> 51,856 tokens`, `+88.43%` | `QUANTIZATION_V11_SUMMARY.json` |
| Quark INT8 C8 throughput | `160.61 vs 253.74 tok/s`, `-36.70%` | `QUANTIZATION_V11_SUMMARY.json` |
| Quark INT8 C128 safety gate | `11/51`, production rejected | `QUANTIZATION_V11_SUMMARY.json` |
| Quark INT4 W4A16 storage | `8.06 -> 2.68 GB`, loader incompatible | `QUARK_QUANTIZATION_W7900_V11.md` |
| Schema-constrained INT8 | JSON `2/12`, semantic admission `0/12` | `ADAPTIVE_PRECISION_V12_SUMMARY.json` |
| Adaptive FP16 fallback | final accepted `12/12` | `ADAPTIVE_PRECISION_V12_SUMMARY.json` |

## Verification and Governance Evidence

| Product evidence | Result | Source |
|---|---|---|
| Real adaptive Voice-to-Proof | Fallback route bound in proof, `mail.send = deny`, `7/7` | `ADAPTIVE_PRECISION_V12_E2E.json` |
| Server-authoritative action contract | Six ordered commands; P2 excluded; email and calendar remain draft-only; browser action replacement ignored | public Voice module; proof `action_contract.json` |
| Sandbox execution proof | Six before/after state hashes, controlled outputs, five probes, zero external effects | public Proof module; proof `sandbox_replay.json` |
| Skill governance lifecycle | Proof-hash-checked promotion, supersede, reasoned revoke, and verified rollback | public Memory module; governance receipts |
| Promotion impact gate | Permission, constraint, action, and runtime diff; risk acknowledgement; stale-review rejection | public Memory module; PROMOTE receipt review hash |
| Governance audit ledger | Previous-hash chain, payload and entry hashes, receipt reconciliation, local modification/deletion detection, JSONL export | public Memory module; `/api/governance/ledger.jsonl` |

## Demo Artifact Boundaries

- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.mp4` records the final public product
  path, including real W7900 inference, promotion, ledger export, and exact
  reuse. It ends with a terminology card that states the package and integrity
  boundaries.
- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4` is supplementary performance
  narration for the same public Radeon path.
- `CONTINUOUS_OPERATION_DEMO_V2.mp4` uses deterministic ASR/compiler fixtures
  while performing real process restarts and durable recovery. It documents
  compatibility, invalidation, and parent-child proof lineage rather than GPU
  performance.

## Evidence Boundaries

- Exact reuse is an application fast path for an identical promoted skill. It
  is excluded from fresh-inference GPU performance claims.
- Voice Evidence values are internal deterministic quality-gate results, not
  external speech-recognition accuracy measurements.
- Ledger hashes are not digital signatures and are not anchored to an external
  immutable service.
- Quark INT8 improved memory capacity but was slower and failed the required
  policy-semantic gate. Production remains FP16.

## Integrity Anchors

- Final Demo V3 MP4:
  `3c7c60bb19f7bd36300682b548416ce2f7cb1d84c7d31f90c6b6922091d69727`
- Final Demo V3 SRT:
  `aaf60da629ba861c3280c7402cdeb83e98526500f53f7f5812d09edf58172534`
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
