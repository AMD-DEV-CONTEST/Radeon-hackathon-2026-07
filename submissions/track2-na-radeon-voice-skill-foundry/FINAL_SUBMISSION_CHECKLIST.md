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
- [x] Current local `npm test`: 56/56 passed
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
- [x] Current local product regression: 56/56, build

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
  `f79628e058e347f39d75fbe0f9cef44c30ed3886a76000b98408b279d33e41dd`
- Refreshed architecture PNG:
  `1feec7ef529232b12c4f4d9bfca6d59f05685bc7253b9aab35efe90688b37fce`
- Refreshed poster PDF:
  `80b1c4fed179510766ffe5118ade2f1281612c0681eccb37d04f31bbf33dd0cb`
- Refreshed poster PNG:
  `ecd45829137ebc7d5bb7e259b77f34e0355474741773ce12914549cdeaf7bf72`

## Evidence Boundary

- Main Demo V2 is the real Cloudflare + W7900 performance and product proof.
- Continuous Demo V2 is deterministic lifecycle evidence with real process
  restarts; it is not used as GPU performance evidence.
- The Chinese SOP WAV is a synthetic reproducible fixture.
- Demo narration uses AIDP `gemini-3.1-flash-tts-preview`, male `Charon`.

## Quark Quantization v11

- [x] Quark INT4 W4A16 export on W7900
- [x] Record vLLM loader incompatibility instead of claiming unsupported serving
- [x] Quark INT8 W8A8 C16 eager and graph
- [x] Quark INT8 W8A8 C128 eager
- [x] Same-hardware FP16 rerun
- [x] C1/2/4/8 throughput matrix
- [x] Model storage, model-load VRAM, KV-cache, telemetry
- [x] Four-part Agent safety semantic gate
- [x] Strict JSON validation on final FP16 and C128 runs
- [x] Production decision: reject INT8 for this policy compiler

Measured result:

- INT4 storage reduction: `66.73%`; serving loader incompatible
- INT8 model-load VRAM reduction: `44.07%`
- INT8 KV-cache increase: `88.43%`
- INT8 C128 C8 throughput: `160.61` versus FP16 `253.74 tokens/s`
- INT8 throughput change: `-36.70%`
- INT8 C128 safety gate: `11/51`
- INT8 C128 strict JSON: `2/51`
- FP16 safety gate and JSON: `51/51`
- Summary SHA-256:
  `06818f8b875594a42681ce7f6e6b024272c1cbc706fa87bb1c59c8fb2a4c8605`
- Evidence ZIP SHA-256:
  `d1317a593f7cabb1e53e255a84b76bd82d6cb0829b53b6974b7d370b1d6fdb06`

## Adaptive Precision Controller v12

- [x] JSON Schema constrained INT8 experiment
- [x] Deterministic safety-kind admission
- [x] Optional FP16 fallback endpoint
- [x] Route and rejection reasons bound into proof core
- [x] Clean W7900 clone: 38/38, typecheck, build
- [x] Real W7900 Voice -> INT8 rejection -> FP16 fallback -> 7/7 -> Proof

Measured result:

- raw INT8 JSON/admission: `0/12`, `0/12`
- schema INT8 JSON/admission: `2/12`, `0/12`
- fallback count: `12/12`
- final accepted: `12/12`
- median adaptive latency: `19.42 s`
- final Voice Evidence: `100/100`
- final permission: `mail.send = deny`
- final verification: `7/7`
- proof hash:
  `c306a612bdfed26a1ba7f69ee14e5cdfd230deafa91617915ba67d7e195bb71c`
- proof ZIP SHA-256:
  `913aa087c35c5f06faeff82845c64733a6208aa51e70e2e87c521c1466f1bfdc`
- summary SHA-256:
  `33846bd2ac82a5a307cde4e3bab20afbefe258bc0b20551fdf9b93225ffe9582`
- evidence ZIP SHA-256:
  `473b059a85f211454fad6bdb27210c3690d4ccfffb2ce471fcaf1d52cae71584`

## Real Demonstration Workspace

- [x] New runs start with an empty action contract
- [x] Six ordered user commands generate six timestamped events
- [x] P2 findings are excluded after filtering
- [x] Missing owner is explicitly marked `needs_confirmation`
- [x] Email remains `draft`; send remains false
- [x] Calendar holds remain tentative and uncommitted
- [x] Exported report uses account aliases and excludes compensation
- [x] Undo and reset invalidate the incomplete trace
- [x] Compile stays disabled until the six-step contract is complete
- [x] Reducer and event-contract tests: 4/4 passed
- [x] Server rejects out-of-order demonstration commands
- [x] Compile resolves the server session instead of trusting browser actions
- [x] Proof and ZIP include the full `action_contract.json`
- [x] Sandbox Replay v1 records six before/after state hashes and output diffs
- [x] Five adversarial probes pass with zero external side effects
- [x] Proof and ZIP include `sandbox_replay.json`
- [x] Proof schema/verifier v0.4 invalidates older replay semantics
- [x] Verified output is saved as a non-reusable promotion candidate
- [x] Promotion binds the current proof hash and supersedes older promoted versions
- [x] Revocation requires a reason and blocks reuse
- [x] Rollback revalidates history and creates a new promoted version
- [x] Promotion, supersede, revoke, and rollback write governance receipts
- [x] Promotion Review compares permissions, constraints, actions, and runtime
- [x] Review hash makes stale approvals fail closed
- [x] Risk escalation requires explicit acknowledgement
- [x] Promotion receipt binds review hash, risk level, and acknowledgement
- [x] Governance Audit Ledger forms an append-only previous-hash chain
- [x] Ledger reconciles governance receipts with procedural memory
- [x] Payload tampering and deleted tail/middle events are detected
- [x] Ledger UI exposes status, issues, head hash, and ordered events
- [x] Full governance chain exports as JSONL
- [ ] Record the final product Demo only after feature and narrative freeze
