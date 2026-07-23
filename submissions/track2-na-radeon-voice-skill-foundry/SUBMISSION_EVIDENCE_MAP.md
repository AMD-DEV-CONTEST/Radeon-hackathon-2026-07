# Submission Evidence Map

This page maps the Track 2 requirements to the submitted product, source, and
reproducible evidence.

## Start Here

1. [Live product](https://radeon-voice-skill-foundry.pages.dev/)
2. [Multi-turn Director Cut, 35.5 seconds](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4)
3. [Raw multi-turn product capture, 32 seconds](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4)
4. [Multi-turn supplement screenshot](MULTI_TURN_INTERACTION_DEMO.png)
5. [Multi-turn interaction brief](MULTI_TURN_INTERACTION.md)
6. [Parent-child lineage](MULTI_TURN_LINEAGE.png)
7. [Product Demo](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4)
8. [Project Specification](PROJECT_SPECIFICATION.pdf)
9. [Technical Evidence Index](TECHNICAL_EVIDENCE_INDEX.md)
10. [Poster](POSTER.pdf)
11. [Source repository](https://github.com/Chengyuann/radeon-voice-skill-foundry)
12. [Continuous integration](https://github.com/Chengyuann/radeon-voice-skill-foundry/actions/workflows/ci.yml)

Runtime and integrity checks:

- [Radeon health](https://radeon-voice-skill-foundry.pages.dev/api/health)
- [Governance sample](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/GOVERNANCE_LEDGER.jsonl)
- [Release checksums](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/SHA256SUMS.txt)

## Multi-Turn Interaction Snapshot

| Stage | Result |
|---|---|
| Parent | verified `revision 1`, run `run_dbc1a6e2c6b5` |
| Correction | require confirmation before creating calendar holds |
| Child | verified `revision 2`, run `run_79b986c46400` |
| Provenance | child `parentRunId` equals the parent run ID |
| Regeneration | `10` constraints and `7` fixtures in the child proof |
| Evidence | [35.5-second Director Cut](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4), [raw 32-second product capture](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4), screenshot, brief, lineage, JSON, and proof ZIP |

## Product Demo Chapters

| Time | Evidence |
|---|---|
| `00:00-00:29` | Product positioning, Cloudflare entry, W7900 and ROCm runtime |
| `00:29-01:17` | Spoken SOP and six server-authoritative actions |
| `01:17-01:53` | Qwen3-ASR and Qwen3 compilation on Radeon |
| `01:53-02:31` | Least-privilege policy, Sandbox Replay, and 7/7 proof |
| `02:31-03:07` | Promotion Impact Review |
| `03:07-03:45` | Governance Audit Ledger and JSONL export |
| `03:45-04:15` | Exact promoted-skill reuse |
| `04:15-04:48` | End-to-end summary and terminology boundary |

## Track 2 Requirement Coverage

| Track 2 requirement | Submitted evidence |
|---|---|
| Clear task positioning and creative scenario | Voice captures conditions, exceptions, and prohibited side effects that are absent from an action trace. See Product Demo `00:00-01:17` and Project Specification sections 1-3. |
| Task decomposition, tools, RAG, and memory | Six typed actions compile into an ordered procedure, deterministic local retrieval, least-privilege permissions, fixtures, proof artifacts, and versioned procedural memory. See Product Demo `00:29-04:15`. |
| Smooth multi-turn interaction | **Watch the [Director Cut](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4):** revision 1 baseline -> correction creates revision 2 -> revision 2 is verified -> another correction creates revision 3 -> verification is required again. It uses real product footage, hard captions, locally generated VoxCPM2 narration, and a project-owned original soundtrack. The raw product capture remains available as primary evidence. |
| Core inference on Radeon and ROCm | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run on a W7900-class `gfx1100` instance with ROCm 7.2.1. See live health, Product Demo, and `evidence/HARDWARE_BENCHMARK.json`. |
| Targeted inference-speed optimization | Compact output reduces model output tokens by 29.42% and generation latency by 30.03%; vLLM graph serving reaches 257.65 aggregate output tokens/s at concurrency 8; native ASR batch 8 reaches 85.35x aggregate real-time. |
| Quantization or other optimization bonus | Quark INT8 reduces model-load VRAM by 44.07% and increases KV-cache capacity by 88.43%, but fails the policy-semantic gate. The adaptive controller rejects all unsafe INT8 outputs and falls back to FP16. This is submitted as a measured, fail-closed optimization study rather than a production quantization claim. |

## Verification Snapshot

- Submission regression suite: `63/63`
- TypeScript typecheck: passed
- Production build: passed
- Audio-backed workflow: `7/7`
- Sandbox Replay: `6/6` transitions and `5/5` fail-closed probes
- Final permission: `mail.send = deny`
- Verified workflow proof: `VERIFIED_WORKFLOW_PROOF.zip`
- Multi-turn interaction brief: `MULTI_TURN_INTERACTION.md`
- Parent-child lineage: `MULTI_TURN_LINEAGE.png`
- Multi-turn refinement proof: `MULTI_TURN_REFINEMENT_PROOF.zip`
- Governance sample: `GOVERNANCE_LEDGER.jsonl`
- Release integrity: `SHA256SUMS.txt`

## Evidence Boundaries

- Exact reuse applies only to an identical promoted skill and is not a
  fresh-inference GPU speedup.
- Voice Evidence is an internal deterministic signal-quality gate, not an ASR
  word-error-rate benchmark.
- The governance ledger is hash-chained and reconciled with skill memory; it is
  not digitally signed or externally anchored.
- Quark INT8 is a rejected production candidate. The direct production route
  remains FP16.
- The recorded `GAIA-compatible` phrase refers to the portable Agent Skill
  Markdown structure and is not a certification claim.
