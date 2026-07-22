# Technical Evidence Index

Scope: submission evidence package

This index connects the implemented product capabilities, Radeon measurements,
verification artifacts, and documented evidence boundaries.

## Project Materials

1. Live product: `https://radeon-voice-skill-foundry.pages.dev/`
2. Product Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Architecture: `ARCHITECTURE.png`
5. Poster: `POSTER.pdf`
6. Radeon evidence: `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json`

## System Capability Map

| Capability | Implementation | Evidence | Demo timestamp | Boundary |
|---|---|---|---|---|
| Voice-seeded workflow capture | Voice records conditions, exceptions, and prohibited side effects that are absent from a UI trace | Project Specification sections 1-3; generated `SKILL.md`, policy, fixtures, and proof ZIP | Product Demo 00:00-00:29 | Synthetic SOP audio is disclosed as a reproducible fixture |
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents | Project Specification sections 4-5; public Memory module; proof ZIP | Product Demo 00:29-04:15 | Retrieval is token-overlap search, not embedding or vector search |
| Tool invocation and planning | Typed tools and six server-accepted actions compile into a multi-step procedure, constraints, permissions, and fixtures | Public Voice and Proof modules; generated policy; proof ZIP | Product Demo 00:29-02:48 | The workspace isolates external side effects |
| Verification and procedural memory | Deterministic replay, five fail-closed probes, versioned memory, promotion, ledger export, and exact reuse | Public Proof and Memory modules; submission `63/63` suite; Product Demo proof and ledger | Product Demo 02:48-04:15 | Reuse applies only to an identical promoted skill |
| Core inference on Radeon | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run on W7900-class `gfx1100` with ROCm 7.2.1 | Live `/api/health`; Radeon audio proof; Product Demo proof ZIP | Product Demo 00:29-01:53 | Real model waiting time is preserved |
| Targeted inference optimization | Same-hardware vLLM serving A/B, native ASR batching, and compact structured output | Radeon experiment summary; source benchmark JSON in the project repository | Performance Demo 03:38-04:13 | Compact-output A/B uses three runs; vLLM C8 is a concurrent serving result |

## Track 2 Capability Coverage

| Capability | Implementation | Evidence |
|---|---|---|
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents, with visible selected evidence | Performance Demo 01:14-01:52; Project Specification 5.1 |
| Tool invocation | Typed file, report, mail, calendar, and network capabilities | Performance Demo 01:54-02:28; generated policy |
| Multi-step planning | Voice and action evidence compile into constraints, a skill, fixtures, and proof | Performance Demo 00:35-02:56 |
| Local memory | Versioned Verified Skill Registry and exact reuse | Performance Demo 03:08-03:36 |
| Permission and privacy controls | Allow, review, and deny decisions; redaction; confirmation; receipts | Performance Demo 01:54-02:56 |

## Measured Radeon Evidence

| Measurement | Result | Source |
|---|---:|---|
| vLLM graph, concurrency 8 | `257.65 output tokens/s` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Serialized Transformers, concurrency 8 | `20.66 output tokens/s` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Same-hardware serving ratio | `12.47x` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Native ASR batch 8 | `85.35x aggregate real-time` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Native ASR batching speedup | `6.659x` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Compact output token reduction | `29.42%` | source optimization benchmark JSON |
| Compact output generation-latency reduction | `30.03%` | source optimization benchmark JSON |
| Identical promoted-skill reuse | `2.18 ms`; avoids a repeat model call | source optimization benchmark JSON |
| Voice Evidence clean sample | `pass / 100` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| 120 ms burst loss | `review / 88` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| 280 ms burst loss | `quarantine / 65` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Quark INT8 model-load VRAM | `7.67 -> 4.29 GiB`, `-44.07%` | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Quark INT8 KV-cache capacity | `27,520 -> 51,856 tokens`, `+88.43%` | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Quark INT8 C8 throughput | `160.61 vs 253.74 tok/s`, `-36.70%` | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Quark INT8 C128 safety gate | `11/51`, production rejected | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Quark INT4 W4A16 storage | `8.06 -> 2.68 GB`, loader incompatible | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Schema-constrained INT8 | JSON `2/12`, semantic admission `0/12` | `evidence/ADAPTIVE_PRECISION_SUMMARY.json` |
| Adaptive FP16 fallback | accepted `12/12` | `evidence/ADAPTIVE_PRECISION_SUMMARY.json` |

## Verification and Governance Evidence

| Product evidence | Result | Source |
|---|---|---|
| Real adaptive Voice-to-Proof | Fallback route bound in proof, `mail.send = deny`, `7/7` | `evidence/ADAPTIVE_PRECISION_E2E.json` |
| Server-authoritative action contract | Six ordered commands; P2 excluded; email and calendar remain draft-only; browser action replacement ignored | public Voice module; proof `action_contract.json` |
| Sandbox execution proof | Six before/after state hashes, controlled outputs, five probes, zero external effects | public Proof module; proof `sandbox_replay.json` |
| Skill governance lifecycle | Proof-hash-checked promotion, supersede, reasoned revoke, and verified rollback | public Memory module; governance receipts |
| Promotion impact gate | Permission, constraint, action, and runtime diff; risk acknowledgement; stale-review rejection | public Memory module; PROMOTE receipt review hash |
| Governance audit ledger | Previous-hash chain, payload and entry hashes, receipt reconciliation, local modification/deletion detection, JSONL export | public Memory module; `/api/governance/ledger.jsonl` |

The bundled `GOVERNANCE_LEDGER.jsonl` is the Product Demo sample and contains
two `PROMOTE` entries. The regression suite covers the implemented supersede,
revoke, and rollback actions.

## Demo Artifact Boundaries

- `RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4` records the public product
  path, including real W7900 inference, promotion, ledger export, and exact
  reuse. It ends with a terminology card that states the package and integrity
  boundaries.
- `RADEON_VOICE_SKILL_FOUNDRY_PERFORMANCE_DEMO.mp4` is supplementary performance
  narration for the same public Radeon path. Its spoken `35/35` count belongs
  to the pinned recording revision.
- `CONTINUOUS_OPERATION_DEMO.mp4` uses deterministic ASR/compiler fixtures
  while performing real process restarts and durable recovery. It documents
  compatibility, invalidation, and parent-child proof lineage rather than GPU
  performance.

## Evidence Boundaries

- Exact reuse is an application fast path for an identical promoted skill. It
  is excluded from fresh-inference GPU performance claims.
- Proof archives preserve their original internal `projectName`, `SKILL.md`
  name, and policy semantic-version fields because those values identify the
  recorded run and participate in artifact verification. They are immutable
  evidence identifiers, not alternate submission deliverables.
- The Product Demo's recorded `GAIA-compatible` phrase refers only to portable
  Agent Skill Markdown. No external GAIA conformance or certification is
  claimed.
- Voice Evidence values are internal deterministic quality-gate results, not
  external speech-recognition accuracy measurements.
- Ledger hashes are not digital signatures and are not anchored to an external
  immutable service.
- Quark INT8 improved memory capacity but was slower and failed the required
  policy-semantic gate. Production remains FP16.

## Integrity Anchors

`SHA256SUMS.txt` contains the SHA-256 digest for every finalized artifact in
the submission package except the checksum manifest itself. It is regenerated
after all documents, media, proofs, and evidence files are finalized.
