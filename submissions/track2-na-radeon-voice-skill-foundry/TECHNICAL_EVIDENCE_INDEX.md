# Technical Evidence Index

Scope: submission evidence package

This index connects the implemented product capabilities, Radeon measurements,
verification artifacts, and documented evidence boundaries.

## Project Materials

1. Judge quickstart: `JUDGE_QUICKSTART.md`
2. Reproducibility: `REPRODUCIBILITY.md`
3. Unedited W7900 evidence:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.mp4`
4. W7900 evidence summary: `W7900_LIVE_EVIDENCE_SUMMARY.json`
5. Public health summary and history:
   `PUBLIC_HEALTH_SUMMARY.json`, `PUBLIC_HEALTH_HISTORY.jsonl`
6. GitHub scheduled health summary:
   `GITHUB_SCHEDULED_HEALTH_SUMMARY.json`
7. Multi-turn interaction: `MULTI_TURN_INTERACTION.md`
8. Multi-turn Director Cut:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4`
9. Raw multi-turn product capture:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4`
10. Multi-turn supplement screenshot: `MULTI_TURN_INTERACTION_DEMO.png`
11. Parent-child lineage: `MULTI_TURN_LINEAGE.png`
12. Agent harness repair evidence: `AGENT_HARNESS_REPAIR_EVIDENCE.json`
13. Agent harness repair proof: `AGENT_HARNESS_REPAIR_PROOF.zip`
14. Submission evidence map: `SUBMISSION_EVIDENCE_MAP.md`
15. Live product: `https://radeon-voice-skill-foundry.pages.dev/`
16. Product Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
17. Project Specification: `PROJECT_SPECIFICATION.pdf`
18. Architecture: `ARCHITECTURE.png`
19. Judge result card: `JUDGE_RESULT_CARD.png`
20. Poster: `POSTER.pdf`
21. Multi-turn refinement: `MULTI_TURN_REFINEMENT.png` and
   `MULTI_TURN_REFINEMENT.json`, with
   `MULTI_TURN_REFINEMENT_PROOF.zip`
22. Radeon evidence: `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json`
23. Live Radeon recovery: `LIVE_RADEON_RECOVERY_EVIDENCE.json`
24. Audio-native policy critic:
   `AUDIO_NATIVE_POLICY_CRITIC_SUMMARY.json`
25. Cross-modal policy induction:
   `CROSS_MODAL_POLICY_INDUCTION.png`

## System Capability Map

| Capability | Implementation | Evidence | Demo timestamp | Boundary |
|---|---|---|---|---|
| Voice-seeded workflow capture | Voice records conditions, exceptions, and prohibited side effects that are absent from a UI trace | Project Specification sections 1-3; generated `SKILL.md`, policy, fixtures, and proof ZIP | Product Demo 00:00-00:29 | Synthetic SOP audio is disclosed as a reproducible fixture |
| Cross-modal policy induction | Private speech supplies hidden intent, demonstrated actions supply real tool/state evidence, local retrieval supplies authority, and audio-native verification cross-checks the original SOP audio; the resulting policy is typed and verified | `CROSS_MODAL_POLICY_INDUCTION.png`; Project Specification section 3; proof `action_contract.json`, `rag_evidence.json`, and `AUDIO_NATIVE_POLICY_CRITIC_SUMMARY.json` | Product Demo 00:00-02:48 | Audio-native critic is research-only and never grants permissions |
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents | Project Specification sections 4-5; public Memory module; proof ZIP | Product Demo 00:29-04:15 | Retrieval is token-overlap search, not embedding or vector search |
| Tool invocation and planning | Typed tools and six server-accepted actions compile into a multi-step procedure, constraints, permissions, and fixtures | Public Voice and Proof modules; generated policy; proof ZIP | Product Demo 00:29-02:48 | The workspace isolates external side effects |
| Multi-turn refinement | A natural-language correction creates revision 2, binds `parentRunId`, and regenerates constraints and fixtures without overwriting the prior run; another correction creates revision 3 and reopens verification | 35.5-second Director Cut with locally generated VoxCPM2 narration; raw 32-second product capture; screenshot; brief; lineage; JSON; child proof ZIP | Director Cut `00:00-00:35.5` | The Director Cut is independent of the 4:49 Product Demo; the raw capture remains the primary product evidence |
| Verification and procedural memory | Deterministic replay, five safety probes, typed harness/verifier contracts, bounded verifier refinement, versioned memory, promotion, ledger export, and exact reuse | Public Proof and Memory modules; submission `68/68` suite; agent harness repair proof; verified workflow proof and ledger | Product Demo 02:48-04:15; repair evidence JSON | Reuse applies only to an identical promoted skill; non-policy findings preserve manual review |
| Core inference on Radeon | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run on W7900-class `gfx1100` with ROCm 7.2.1 | Live `/api/health`; Radeon audio proof; verified workflow proof ZIP | Product Demo 00:29-01:53 | Real model waiting time is preserved |
| Unedited W7900 execution | One continuous public run shows health, ASR, primary-model compile, 7/7 verification, and the full proof hash | 48.96-second raw WebM/MP4; `W7900_LIVE_EVIDENCE_SUMMARY.json` | Unedited capture 00:00-00:48.96 | MP4 is a full-length codec transcode only |
| Public stable-URL operation | External launchd monitor validates HTTP 200 and model/ASR dependency health | `PUBLIC_HEALTH_SUMMARY.json`; `PUBLIC_HEALTH_HISTORY.jsonl` | N/A | 187.6-minute captured interval, 39/39 healthy |
| Independent cloud health checks | GitHub Actions validates Radeon mode plus model and ASR dependencies outside the W7900 and local Mac process trees | `GITHUB_SCHEDULED_HEALTH_SUMMARY.json`; workflow run links | N/A | 29/29 scheduled checks over 50.75 observed hours; schedule is best-effort and observed executions are reported exactly |
| Allocation continuity | Radeon Cloud Profile still showed 5 credits available and 0 consumed after 54.76 hours | `LIVE_RADEON_RECOVERY_EVIDENCE.json` | N/A | Platform allocation policy remains organizer-controlled |
| Targeted inference optimization | Same-hardware vLLM serving A/B, GPU package-energy integration, native ASR batching, and compact structured output | Radeon experiment summary; `evidence/BOARD_ENERGY_SUMMARY.json`; source benchmark JSON in the project repository | Performance Demo 03:38-04:13 | Board energy excludes CPU, RAM, cooling, and PUE; vLLM C8 is a concurrent serving result |
| Audio-native policy cross-check | Qwen2.5-Omni-3B listens to the original SOP audio and independently proposes typed policy rules without using the ASR transcript | `AUDIO_NATIVE_POLICY_CRITIC_SUMMARY.json`; reproducible experiment scripts | N/A | Research-only critic under the Qwen Research License; it never grants permissions or replaces the production pipeline |

## Track 2 Capability Coverage

| Capability | Implementation | Evidence |
|---|---|---|
| Local knowledge retrieval | Deterministic token-overlap retrieval over local policy and SOP documents, with visible selected evidence | Performance Demo 01:14-01:52; Project Specification 5.1 |
| Tool invocation | Typed file, report, mail, calendar, and network capabilities | Performance Demo 01:54-02:28; generated policy |
| Multi-step planning | Voice and action evidence compile into constraints, a skill, fixtures, and proof | Performance Demo 00:35-02:56 |
| Smooth multi-turn interaction | Natural-language policy correction produces a child revision with explicit parent lineage and a new verified proof; another correction creates the next child and reopens verification | 35.5-second Director Cut; raw capture; screenshot; brief; lineage; proof ZIP; Project Specification 5.4 |
| Local memory | Versioned Verified Skill Registry and exact reuse | Performance Demo 03:08-03:36 |
| Permission and privacy controls | Allow, review, and deny decisions; redaction; confirmation; receipts | Performance Demo 01:54-02:56 |

## Measured Radeon Evidence

| Measurement | Result | Source |
|---|---:|---|
| vLLM graph, concurrency 8 | `257.65 output tokens/s` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Serialized Transformers, concurrency 8 | `20.66 output tokens/s` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| Same-hardware serving ratio | `12.47x` | `evidence/RADEON_SERVING_AND_ASR_SUMMARY.json` |
| vLLM graph board-energy reduction | `78.76%` over the fixed 51-request workload | `evidence/BOARD_ENERGY_SUMMARY.json` |
| vLLM graph output-token board efficiency | `0.6195 tok/J`, `4.79x` Transformers | `evidence/BOARD_ENERGY_SUMMARY.json` |
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
| Precision admission gate | FP16 selected for production semantics | `evidence/QUARK_QUANTIZATION_SUMMARY.json`; `evidence/ADAPTIVE_PRECISION_SUMMARY.json` |
| Quark INT4 W4A16 storage | `8.06 -> 2.68 GB`, loader incompatible | `evidence/QUARK_QUANTIZATION_SUMMARY.json` |
| Schema-constrained INT8 | JSON `2/12`, semantic admission `0/12` | `evidence/ADAPTIVE_PRECISION_SUMMARY.json` |
| Production precision route | FP16 accepted `12/12` | `evidence/ADAPTIVE_PRECISION_SUMMARY.json` |

## Verification and Governance Evidence

| Product evidence | Result | Source |
|---|---|---|
| Real adaptive Voice-to-Proof | Selected route bound in proof, `mail.send = deny`, `7/7` | `evidence/ADAPTIVE_PRECISION_E2E.json` |
| Server-authoritative action contract | Six ordered commands; P2 excluded; email and calendar remain draft-only; browser action replacement ignored | public Voice module; proof `action_contract.json` |
| Sandbox execution proof | Six before/after state hashes, controlled outputs, five probes, zero external effects | public Proof module; proof `sandbox_replay.json` |
| Skill governance lifecycle | Proof-hash-checked promotion, supersede, reasoned revoke, and verified rollback | public Memory module; governance receipts |
| Promotion impact gate | Permission, constraint, action, and runtime diff; risk acknowledgement; stale-review rejection | public Memory module; PROMOTE receipt review hash |
| Governance audit ledger | Previous-hash chain, payload and entry hashes, receipt reconciliation, local modification/deletion detection, JSONL export | public Memory module; `/api/governance/ledger.jsonl` |
| Agent harness contract | Server-authoritative tool, context, memory, skill, sandbox, subagent, and budget declarations; harness hash bound into proof compatibility | `AGENT_HARNESS_REPAIR_PROOF.zip/harness.json`; proof bundle |
| Independent verifier contract | Completion criteria, repairability, manual-only categories, server-side isolation, and verifier hash | `AGENT_HARNESS_REPAIR_PROOF.zip/verifier.json`; proof bundle |
| Bounded verifier refinement | Permission-stress input produces structured feedback; revision 2 preserves parent guardrails and verifies with `mail.send = deny` | `AGENT_HARNESS_REPAIR_EVIDENCE.json`; `repair_cycle.json` in proof ZIP |
| Live service recovery | Controlled dependency, tunnel, and supervisor drills restore healthy public service; dual origins and mutual watchdog coverage keep recovery independent of the main service tree | `LIVE_RADEON_RECOVERY_EVIDENCE.json`; `scripts/rvsf_supervisor_watchdog.sh`; `scripts/radeon_rc_tunnel_supervisor.sh`; public `/api/health` |

The bundled `GOVERNANCE_LEDGER.jsonl` is a verified workflow sample with one
`PROMOTE` entry. The regression suite covers the implemented supersede, revoke,
and rollback actions.

## Demo Artifact Boundaries

- `RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4` is the primary 4:49 contest video. It
  records the public product path, including real W7900 inference, promotion,
  ledger export, and exact reuse. It ends with a terminology card that states
  the package and integrity boundaries.
- `RADEON_VOICE_SKILL_FOUNDRY_PERFORMANCE_DEMO.mp4` is supplementary performance
  narration for the same public Radeon path. Its spoken `35/35` count belongs
  to the pinned recording revision.
- `CONTINUOUS_OPERATION_DEMO.mp4` uses deterministic ASR/compiler fixtures
  while performing real process restarts and durable recovery. It documents
  compatibility, invalidation, and parent-child proof lineage rather than GPU
  performance.
- `W7900_LIVE_EVIDENCE_UNEDITED.mp4` and its WebM source are supplementary,
  silent runtime evidence; the external SRT labels each recorded stage.

## Audio-Native Policy Critic Experiment

An isolated W7900 experiment evaluated `Qwen/Qwen2.5-Omni-3B` as an
audio-native policy critic. The model consumed the original 20.39-second
Chinese SOP WAV directly, with no ASR transcript supplied.

- BF16, SDPA, Talker disabled
- model revision `f75b40e3da2003cdd6e1829b1f420ca70797c34e`
- median strict-prompt inference: `9.171 seconds`
- maximum strict-prompt allocated VRAM: `9.108 GiB`
- strict taxonomy admission: `3/3`
- clean, pink-noise, and alert-tone variants preserved all four required
  safety kinds

With explicit taxonomy guidance, clean/noise/alert variants all preserved
`deny`, `redact`, `requires_confirmation`, and `only_if` correctly. Qwen3-ASR
plus Qwen3-4B remains the production path, while the Omni model is used only as
an independent research critic.

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
- Precision admission measured Quark INT8 memory gains and selected FP16 for
  the production route because it preserved policy semantics.

## Integrity Anchors

`SHA256SUMS.txt` contains the SHA-256 digest for every finalized artifact in
the submission package except the checksum manifest itself. It is regenerated
after all documents, media, proofs, and evidence files are finalized.
