# Final Submission Checklist

Deadline: 2026-08-06 23:59 UTC+8.

## Eligibility

- [x] Luma registration approved
- [x] AMD Developer Program registered
- [x] Radeon Cloud credits available
- [x] Solo entry; PR team name is `N/A`
- [x] GitHub ID: `Chengyuann`
- [x] Discord/WeChat joined

## Track 2 Main Rubric

- [x] Clear private-Agent positioning and differentiated scenario
- [x] Local RAG
- [x] Tool invocation
- [x] Multi-step planning
- [x] Local multi-turn/procedural memory
- [x] Permission and privacy controls
- [x] Smooth Voice -> Policy -> Proof -> Memory workflow
- [x] Core Agent inference on AMD Radeon + ROCm
- [x] Local ASR on AMD Radeon + ROCm
- [x] Targeted Radeon inference optimization
- [x] Machine-readable raw benchmark evidence
- [x] Scoring evidence matrix and judge reading path

## Required Deliverables

- [x] Complete public source repository
- [x] English README with environment, dependencies, startup, and verification
- [x] English Project Specification Markdown
- [x] English Project Specification PDF
- [x] Agent architecture diagram
- [x] Supplementary poster
- [x] Recommended 4:48 real-operation Demo V2
- [x] Male TTS narration
- [x] Burned-in English captions and embedded subtitle track
- [x] Matching public SRT
- [x] Public Demo V2 proof ZIP
- [x] Continuous lifecycle Demo V2
- [x] Public interactive Cloudflare entry point
- [x] Official English pull request

## Current Quality Gates

- [x] `npm run typecheck`: passed
- [x] Current local `npm test`: 36/36 passed
- [x] Current local production build: passed
- [x] Public Cloudflare page: HTTP 200
- [x] Public `/api/health`: Radeon mode, W7900-class `gfx1100`, ROCm 7.2.1
- [x] Public real workflow: Voice Evidence v0.3 `100/100`
- [x] Public real workflow: `mail.send = deny`
- [x] Public real workflow: 7/7 verification fixtures
- [x] Public real workflow: save/reuse and proof ZIP
- [x] Continuous V2: two real Node API restarts
- [x] Continuous V2: durable recovery and runtime invalidation
- [x] Continuous V2: child proof binds `parentRunId`, `revision: 2`, and drifted runtime
- [x] Secret scan passed
- [x] Proof ZIP integrity passed

## Radeon Validation Snapshots

- [x] Final audio-backed Radeon snapshot commit `c759a41`: 21/21, build, 7/7
- [x] Durable lifecycle Radeon snapshot commit `efec128`: 29/29, build
- [x] Weekend v10 Radeon snapshot commit `20776d9`: 33/33, build
- [x] Current local continuous-lifecycle regression: 36/36, build

These counts belong to different pinned revisions and are intentionally not
presented as one remote run.

## Official Repository Submission

- [x] Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`
- [x] Branch `codex/track2-radeon-voice-skill-foundry`
- [x] Submission directory:
  `submissions/track2-na-radeon-voice-skill-foundry/`
- [x] PR title: `Track 2, N/A, Radeon Voice Skill Foundry`
- [x] PR #7 is open and mergeable
- [x] Public links verified

Official PR:
`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`

## Primary Evidence Values

- Live product:
  `https://radeon-voice-skill-foundry.pages.dev/`
- GPU: Radeon Pro W7900-class, `gfx1100`, 47.98 GiB VRAM
- ROCm: 7.2.1
- Agent: Qwen3-4B-Instruct-2507
- ASR: Qwen3-ASR-0.6B
- Final permission: `mail.send = deny`
- Verification: 7/7
- Voice Evidence v0.3: clean `pass / 100`
- vLLM graph concurrency-eight: `257.65 tokens/s`
- Transformers concurrency-eight: `20.66 tokens/s`
- Serving uplift: `12.47x`
- ASR batch-eight: `85.35x aggregate real-time`
- ASR batch speedup: `6.659x`
- Compact output token reduction: `29.42%`
- Compact output generation-latency reduction: `30.03%`
- Exact reuse HTTP median: `2.18 ms`
- Measured identical-skill fast path: `11,052.03x`

## Published Integrity Anchors

- Main Demo V2 MP4:
  `87fa6304819f01f5c5861d685a9f0c048d71e2e909ab4c9ab133428833125133`
- Main Demo V2 SRT:
  `4c29f3a3922226602ab2fa0d33f1dd30bc6b7341fc4e8028c5b4d959cbc9cec4`
- Main Demo V2 proof ZIP:
  `b9d81491e3292ce0190f6042aefbc3de19f9cf236fc6ef3c0dc9cf72b06c61c5`
- Continuous Demo V2 MP4:
  `98c8b56fbc92c80376fabc0b0386a9ed2ecb9b5c97c25ddefebd6c80d2a4b243`
- Continuous Demo V2 SRT:
  `8bab8c8879fdbd86dc2770e01f6e7193d10ce36025b10aedc8c3e4d7170031f4`
- Continuous Demo V2 child proof:
  `f27b8298e64b588f12a200104c65d7ea3c42ff690c2d2067a62e261ddd3c4a36`
- Final Radeon audio proof ZIP:
  `6ea53dfe28f8221b3db9b06e6eed537767bf28b4c6536d25d45f3ffec20500e9`
- Weekend v10 summary:
  `4871e76d1d0204c5d0179418132ed778f53b8adc6a230120d2974ff61be7158a`
- Weekend v10 evidence ZIP:
  `1189e0e47c14ba18784f5be82aa5c68366946c0d6378d6a8d26adef61dfd3e9b`
- Refreshed Project Specification PDF:
  `571985eeac51ea45cfe615d6aa8287fae49d1c3b195f140bd812c77e0b8a02ee`
- Refreshed architecture PNG:
  `1feec7ef529232b12c4f4d9bfca6d59f05685bc7253b9aab35efe90688b37fce`
- Refreshed poster PDF:
  `d07c500c6f964a856ab0af3821cc13af91aa4bd71d5d21bd00db0c8aecabbca1`
- Refreshed poster PNG:
  `ecd45829137ebc7d5bb7e259b77f34e0355474741773ce12914549cdeaf7bf72`

## Evidence Boundary

- Main Demo V2 is the real Cloudflare + W7900 performance and product proof.
- Continuous Demo V2 is deterministic lifecycle evidence with real process
  restarts; it is not used as GPU performance evidence.
- The Chinese SOP WAV is a synthetic reproducible fixture.
- Demo narration uses AIDP `gemini-3.1-flash-tts-preview`, male `Charon`.

## Optional Bonus Gap

- [ ] Quark INT8/FP8 or equivalent quantized same-hardware A/B

No quantization result is claimed. The current submission has direct evidence
for the 100-point main rubric; quantization remains optional bonus work.
