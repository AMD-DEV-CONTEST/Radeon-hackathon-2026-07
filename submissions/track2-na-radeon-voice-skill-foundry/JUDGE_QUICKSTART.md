# Judge Quickstart

This page is the shortest path through Radeon Voice Skill Foundry.

## 1. Watch These First

1. Primary contest Product Demo, 4:49:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
2. Supplementary unedited live W7900 proof, 48.96 seconds:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.mp4`
   Raw browser capture and English stage captions:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.webm`
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.srt`
3. Multi-turn Director Cut, 35.5 seconds:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4`

The Product Demo is the authoritative 3-5 minute contest video. The unedited
capture independently proves one continuous public request sequence:
`health -> ASR -> compile -> verify -> proof hash`. The Director Cut isolates
multi-turn revision behavior.

Video delivery audit: every Release media asset matched `SHA256SUMS.txt` and
decoded fully. The 4:49 Product Demo is H.264 1080p with AAC narration,
burned-in captions, an embedded English subtitle track, and the matching
external SRT. Its measured duration is 288.58 seconds.

## 2. Score Map

| Track 2 area | Fast evidence |
|---|---|
| Judge-facing result summary | `JUDGE_RESULT_CARD.png`: three evidence channels -> verified Agent Skill; least-privilege decisions; 7/7 verification; four headline metrics |
| Local RAG | Product Demo `00:29-04:15`; proof `rag_evidence.json` |
| Cross-modal policy induction | `CROSS_MODAL_POLICY_INDUCTION.png`: Heard + Observed + Retrieved -> typed least-privilege policy |
| Tool invocation | Six server-authoritative actions in `action_contract.json` |
| Multi-step planning | Generated `SKILL.md`, `policy.yaml`, fixtures, and sandbox replay |
| Smooth multi-turn interaction | 35.5-second Director Cut; `MULTI_TURN_REFINEMENT_PROOF.zip` |
| Local memory | Promotion review, governance ledger, and exact reuse in Product Demo |
| Permission and privacy | `mail:send = deny`, redaction, and five safety probes |
| Agent infrastructure | `AGENT_HARNESS_REPAIR_EVIDENCE.json` and `AGENT_HARNESS_REPAIR_PROOF.zip` |
| Radeon optimization | vLLM concurrency, board-energy integration, ASR batching, compact output, precision admission |
| Board-energy efficiency | `evidence/BOARD_ENERGY_SUMMARY.json`: fixed 51-request workload, `-78.76%` GPU package energy and `4.79x` output tok/J |
| Live W7900 execution | 48.96-second unedited capture and `W7900_LIVE_EVIDENCE_SUMMARY.json` |
| Public stability | `PUBLIC_HEALTH_SUMMARY.json` and `PUBLIC_HEALTH_HISTORY.jsonl` |

## 3. One-command Verification

From the source repository root:

```bash
npm ci
npm run verify:submission
```

The verification command regenerates the agent-harness repair evidence, runs
the 68-test suite, typechecks, builds the production frontend, checks every
submission artifact in `SHA256SUMS.txt`, and verifies that the Project
Specification PDF contains the current P0 evidence.

## 4. Most Important Proofs

- `VERIFIED_WORKFLOW_PROOF.zip`: authoritative workflow proof.
- `MULTI_TURN_REFINEMENT_PROOF.zip`: child revision proof.
- `AGENT_HARNESS_REPAIR_PROOF.zip`: harness, verifier, structured feedback,
  repair cycle, and final child proof.
- `GOVERNANCE_LEDGER.jsonl`: hash-chained promotion ledger sample.
- `LIVE_RADEON_RECOVERY_EVIDENCE.json`: current W7900 public-health,
  ASR, compile, verify, dependency restart, dual-tunnel failover, and
  tunnel-rotation evidence.
- `W7900_LIVE_EVIDENCE_SUMMARY.json`: hashes, runtime, timings, 7/7 result,
  and proof hash for the 48.96-second unedited live capture.
- `PUBLIC_HEALTH_SUMMARY.json` and `PUBLIC_HEALTH_HISTORY.jsonl`: more than
  three hours of external stable-URL health samples.
- `GITHUB_SCHEDULED_HEALTH_SUMMARY.json`: independently scheduled cloud checks
  with observed run times and explicit GitHub scheduling boundaries.
- `AUDIO_NATIVE_POLICY_CRITIC_SUMMARY.json`: raw-audio Qwen2.5-Omni-3B
  cross-check, including 3/3 admitted strict clean/noise/alert variants.
- `JUDGE_RESULT_CARD.png`: the first-screen visual summary of why this is not
  speech-to-text-to-chat and which four measurements judges should remember.
- `CROSS_MODAL_POLICY_INDUCTION.png`: why speech, demonstrated actions, local
  policy evidence, and audio-native verification are non-interchangeable.
- `SHA256SUMS.txt`: SHA-256 digest for every finalized artifact except itself.

## 5. Boundaries

- Exact reuse is an application fast path for an identical promoted skill, not
  a fresh-inference GPU speedup.
- Voice Evidence is an internal deterministic signal-quality gate, not an ASR
  word-error-rate benchmark.
- Precision admission measured Quark INT8 memory savings and selected FP16 for
  the production route.
- Ledger entries are SHA-256 chained but not digitally signed or externally
  anchored.
