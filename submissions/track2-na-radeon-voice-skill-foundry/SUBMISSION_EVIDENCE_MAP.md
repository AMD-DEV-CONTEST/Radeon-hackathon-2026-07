# Submission Evidence Map

This page maps the Track 2 requirements to the submitted product, source, and
reproducible evidence.

## Start Here

1. [Live product](https://radeon-voice-skill-foundry.pages.dev/)
2. [Primary contest Product Demo, 4:49](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4)
3. [Supplementary unedited W7900 proof, 48.96 seconds](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.mp4)
4. [Raw unedited browser capture](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.webm)
5. [Unedited proof stage captions](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.srt)
6. [W7900 live evidence summary](W7900_LIVE_EVIDENCE_SUMMARY.json)
7. [Public health summary](PUBLIC_HEALTH_SUMMARY.json)
8. [Public health history](PUBLIC_HEALTH_HISTORY.jsonl)
9. [GitHub scheduled health summary](GITHUB_SCHEDULED_HEALTH_SUMMARY.json)
10. [Judge quickstart](JUDGE_QUICKSTART.md)
11. [Reproducibility](REPRODUCIBILITY.md)
12. [Multi-turn Director Cut, 35.5 seconds](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4)
13. [Raw multi-turn product capture, 32 seconds](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4)
14. [Multi-turn supplement screenshot](MULTI_TURN_INTERACTION_DEMO.png)
15. [Multi-turn interaction brief](MULTI_TURN_INTERACTION.md)
16. [Parent-child lineage](MULTI_TURN_LINEAGE.png)
17. [Agent harness repair evidence](AGENT_HARNESS_REPAIR_EVIDENCE.json)
18. [Agent harness repair proof](AGENT_HARNESS_REPAIR_PROOF.zip)
19. [Project Specification](PROJECT_SPECIFICATION.pdf)
20. [Technical Evidence Index](TECHNICAL_EVIDENCE_INDEX.md)
21. [Judge result card](JUDGE_RESULT_CARD.png)
22. [Poster](POSTER.pdf)
23. [Source repository](https://github.com/Chengyuann/radeon-voice-skill-foundry)
24. [Continuous integration](https://github.com/Chengyuann/radeon-voice-skill-foundry/actions/workflows/ci.yml)
25. [Audio-native policy critic summary](AUDIO_NATIVE_POLICY_CRITIC_SUMMARY.json)
26. [Cross-modal policy induction diagram](CROSS_MODAL_POLICY_INDUCTION.png)

Runtime and integrity checks:

- [Radeon health](https://radeon-voice-skill-foundry.pages.dev/api/health)
- [Governance sample](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/GOVERNANCE_LEDGER.jsonl)
- [Release checksums](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/SHA256SUMS.txt)

One-command source verification:

```bash
npm ci
npm run verify:submission
```

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

## Agent Harness and Verify-in-the-Loop Snapshot

| Stage | Result |
|---|---|
| Harness | server-authoritative tools, context, memory, sandbox, and execution budgets |
| Verifier | independent completion criteria, server-side isolation, structured findings |
| Stress input | permission drift toward `mail:send = allow` |
| Attempt 0 | verifier identifies a repairable permission finding |
| Repair | server-generated instruction; parent guardrails preserved |
| Attempt 1 | verifier child revision 2 passes with `mail:send = deny` |
| Budget | at most 2 repair attempts |
| Evidence | `AGENT_HARNESS_REPAIR_EVIDENCE.json` and `AGENT_HARNESS_REPAIR_PROOF.zip` |

## Track 2 Requirement Coverage

| Track 2 requirement | Submitted evidence |
|---|---|
| Clear task positioning and creative scenario | Voice captures conditions, exceptions, and prohibited side effects that are absent from an action trace. See Product Demo `00:00-01:17` and Project Specification sections 1-3. |
| Cross-modal differentiation | Speech explains why/when/never, demonstrated actions prove tools and state, local policy supplies authority, and audio-native verification independently checks the original SOP audio. See `JUDGE_RESULT_CARD.png` and `CROSS_MODAL_POLICY_INDUCTION.png`. |
| Task decomposition, tools, RAG, and memory | Six typed actions compile into an ordered procedure, deterministic local retrieval, least-privilege permissions, fixtures, proof artifacts, and versioned procedural memory. New proofs also bind a typed agent harness and independent verifier contract. See Product Demo `00:29-04:15` and `AGENT_HARNESS_REPAIR_PROOF.zip`. |
| Smooth multi-turn interaction | **Watch the [Director Cut](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4):** revision 1 baseline -> correction creates revision 2 -> revision 2 is verified -> another correction creates revision 3 -> verification is required again. It uses real product footage, hard captions, locally generated VoxCPM2 narration, and a project-owned original soundtrack. The raw product capture remains available as primary evidence. |
| Core inference on Radeon and ROCm | Qwen3-ASR-0.6B and Qwen3-4B-Instruct-2507 run on a W7900-class `gfx1100` instance with ROCm 7.2.1. See live health, Product Demo, and `evidence/HARDWARE_BENCHMARK.json`. |
| Targeted inference-speed optimization | Compact output reduces model output tokens by 29.42% and generation latency by 30.03%; vLLM graph serving reaches 257.65 aggregate output tokens/s at concurrency 8, improves bounded GPU package output-token efficiency by 4.79x, and reduces fixed-workload board energy by 78.76%; native ASR batch 8 reaches 85.35x aggregate real-time. |
| Quantization or other optimization bonus | Precision admission measured 44.07% lower model-load VRAM and 88.43% larger KV-cache capacity for Quark INT8, then selected FP16 for the production route because it preserved policy semantics. |

## Verification Snapshot

- Submission regression suite: `68/68`
- Unedited W7900 run: `48.96 seconds`, health -> ASR -> compile -> verify ->
  proof hash `4181034f...f5510`
- External stable-URL history: `187.6 minutes`, `39/39` healthy, `0` failures
- GitHub scheduled cloud checks: see `GITHUB_SCHEDULED_HEALTH_SUMMARY.json`;
  `29/29` scheduled checks succeeded over `50.75` observed hours without
  claiming exact 15-minute execution.
- Radeon Cloud allocation: `54.76 hours`, `5` credits available, `0` consumed
  at the August 4 profile check.
- Dual public origins: Radeon Cloud `rc-tunnel` primary plus Cloudflare Quick
  Tunnel fallback; each tunnel was stopped independently while Pages health
  remained HTTP 200.
- Audio-native research critic: Qwen2.5-Omni-3B consumed the original SOP WAV
  directly; 3/3 strict taxonomy variants passed under clean/noise/alert
  conditions.
- Live Radeon recovery: `LIVE_RADEON_RECOVERY_EVIDENCE.json`
- TypeScript typecheck: passed
- Production build: passed
- Audio-backed workflow: `7/7`
- Sandbox Replay: `6/6` transitions and `5/5` safety probes
- Final permission: `mail.send = deny`
- Verified workflow proof: `VERIFIED_WORKFLOW_PROOF.zip`
- Multi-turn interaction brief: `MULTI_TURN_INTERACTION.md`
- Parent-child lineage: `MULTI_TURN_LINEAGE.png`
- Multi-turn refinement proof: `MULTI_TURN_REFINEMENT_PROOF.zip`
- Agent harness repair evidence: `AGENT_HARNESS_REPAIR_EVIDENCE.json`
- Agent harness repair proof: `AGENT_HARNESS_REPAIR_PROOF.zip`
- Judge quickstart: `JUDGE_QUICKSTART.md`
- Reproducibility: `REPRODUCIBILITY.md`
- Governance sample: `GOVERNANCE_LEDGER.jsonl`
- Release integrity: `SHA256SUMS.txt`

## Evidence Boundaries

- Exact reuse applies only to an identical promoted skill and is not a
  fresh-inference GPU speedup.
- Voice Evidence is an internal deterministic signal-quality gate, not an ASR
  word-error-rate benchmark.
- The governance ledger is hash-chained and reconciled with skill memory; it is
  not digitally signed or externally anchored.
- Precision admission measured Quark INT8 memory gains and selected FP16 for
  the production route because it preserved policy semantics.
- The recorded `GAIA-compatible` phrase refers to the portable Agent Skill
  Markdown structure and is not a certification claim.
