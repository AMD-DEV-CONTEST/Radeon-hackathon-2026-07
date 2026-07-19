# Radeon Voice Skill Foundry - Track 2 Submission

**Speak the SOP. Prove the Skill.**

Radeon Voice Skill Foundry turns a private spoken SOP and an aligned workflow
demonstration into a verified, reusable Agent Skill before the Agent is allowed
to perform risky actions.

## Entry

- Track: Track 2 - Localized Private AI Agents
- Team: N/A (solo)
- GitHub ID: `Chengyuann`
- Project repository:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry`
- License: MIT
- Live product:
  `https://radeon-voice-skill-foundry.pages.dev/`
- Recommended live Demo V2:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4`
- Demo V2 captions:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.srt`
- Demo V2 proof:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/demo-v2-proof.zip`
- Original overview video:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
- Official submission PR:
  `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`
- Continuous lifecycle Demo V2:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/CONTINUOUS_OPERATION_DEMO_V2.mp4`
- Continuous Demo V2 captions:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/CONTINUOUS_OPERATION_DEMO_V2.srt`
- Continuous Demo V2 child proof:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/continuous-demo-v2-proof.zip`
- Original continuous operation demo:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/CONTINUOUS_OPERATION_DEMO.mp4`

## Why It Matters

Action traces capture what an expert did. Voice captures why, when, exceptions,
privacy boundaries, and what must never happen.

The system compiles both signals into:

- typed SOP constraints
- least-privilege capability policy
- positive and adversarial fixtures
- deterministic verification
- governance receipts
- a hash-bound proof bundle
- a versioned Verified Skill that can be reused without replanning

## Submission Materials

- `PROJECT_SPECIFICATION.pdf` - required English project specification
- `PROJECT_SPECIFICATION.md` - accessible source version
- `SCORING_EVIDENCE_MATRIX.md` - rubric-to-proof judge navigation
- `ARCHITECTURE.png` - Agent architecture diagram
- `POSTER.pdf` - supplementary one-page poster
- `POSTER.png` - poster preview
- `VIDEO_COVER_V2.png` - cinematic 16:9 video cover
- `PROMO_BANNER_V2.png` - 16:9 campaign banner
- `SOCIAL_CARD_V2.png` - square social campaign card
- `DEMO_SCRIPT.md` - 3-5 minute English demo narration and shot list
- `DEMO_NARRATION.md` - final AI-generated English voiceover text
- `DEMO_V2_NARRATION.md` - live Cloudflare + W7900 Demo V2 narration
- `RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.srt` - Demo V2 captions
- `RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt` - final captions
- `CONTINUOUS_OPERATION_DEMO.srt` - continuous workflow captions
- `CONTINUOUS_DEMO_NARRATION.md` - continuous workflow narration source
- `CONTINUOUS_OPERATION_DEMO_V2.srt` - lifecycle Demo V2 captions
- `CONTINUOUS_DEMO_V2_NARRATION.md` - lifecycle Demo V2 narration source
- `FINAL_SUBMISSION_CHECKLIST.md` - completion and evidence ledger

## Measured Radeon Evidence

- GPU: Radeon Pro W7900-class, `gfx1100`, 47.98 GiB VRAM
- ROCm: 7.2.1
- Agent: Qwen3-4B-Instruct-2507, Transformers FP16
- Agent median TTFT: 108.87 ms
- Agent median throughput: 22.02 tokens/s
- ASR: Qwen3-ASR-0.6B
- ASR warm median RTF: 0.0556, approximately 17.98x real-time
- compact output protocol: 29.42% fewer output tokens
- compact output protocol: 30.03% lower generation latency
- exact Verified Skill reuse: 2.18 ms median HTTP round-trip
- full optimized compilation: 24.09 s HTTP round-trip
- exact-reuse speedup for the measured skill: 11,052.03x
- final permission decision: `mail.send = deny`
- original Radeon workflow verification: 6/6 fixtures passed
- local audio-backed proof: 7/7, including Voice Evidence Gate
- final Radeon audio-backed proof: 7/7, including Voice Evidence Gate
- final Radeon validation commit: `c759a41`
- final proof hash:
  `6ff30ccc2d052e226051fa6819760abe3b2c2ef6243b63169ab9d5e0caebfc40`
- final proof ZIP SHA-256:
  `6ea53dfe28f8221b3db9b06e6eed537767bf28b4c6536d25d45f3ffec20500e9`
- vLLM graph concurrency-eight: 257.65 aggregate output tokens/s
- same-model serialized Transformers: 20.66 aggregate output tokens/s
- measured serving uplift: 12.47x
- native ASR batch-eight: 85.35x aggregate real-time
- current local regression suite: 42/42, typecheck, production build
- real deterministic teaching workspace: six user operations generate the
  action trace; no preset trace is attached to a new run

Raw measurements are in:

- `benchmarks/w7900-2026-07-17.json`
- `benchmarks/optimization-w7900-2026-07-17.json`
- `benchmarks/radeon-audio-proof-v8-2026-07-18.json`
- `benchmarks/lifecycle-enhancements-v9-2026-07-18.json`
- `benchmarks/weekend-v10-summary.json`

## Current External Deliverable Status

- Source repository: complete
- English specification: complete
- Architecture diagram: complete
- Poster: complete
- Demo script: complete
- Demo video URL: complete
- Official hackathon PR: open and publicly verified
- Scoring evidence matrix: complete

The final narration uses AIDP `gemini-3.1-flash-tts-preview`, male voice
`Charon`. Both demo MP4 files contain burned-in English narration captions and
an embedded English subtitle track; matching SRT files are also published.
Visual campaign backgrounds were generated with AIDP GPT Image 2; all visible
project typography and measured values were composed locally.

Demo V2 records the current cinematic module UI from the public Cloudflare
deployment. It executes the real Voice -> Policy -> Proof -> Memory workflow
against W7900 Qwen3-ASR and Qwen3-4B, then shows the measured vLLM and ASR
batching evidence.

The current product now adds a real deterministic teaching workspace after
Demo V2: six user commands create the timestamped action contract instead of
attaching the repository preset trace. A refreshed product video remains a
later submission-polish task; the existing Main Demo V2 remains the
authoritative real W7900 inference recording.

Continuous Demo V2 isolates lifecycle control from the performance claim. It
uses deterministic ASR and compiler fixtures, while executing real Node API
process restarts, durable recovery, runtime drift, proof invalidation,
revalidation, and child-proof download in one continuous browser session.

## Post-Submission Engineering Upgrade

- Voice Evidence v0.3 adds estimated SNR, noise floor, speech level, crest
  factor, DC offset, short-dropout, multi-frame burst-loss, and channel
  imbalance diagnostics.
- Server-authoritative evidence, compile runs, and verification results persist
  across service restart.
- Every proof carries a compatibility manifest for verifier, runtime, tools,
  policy, skill, and voice-evidence schema.
- Changed runtime identity marks a skill `revalidation_required`; one-click
  revalidation creates a new child run before reuse is restored.
- Current local regression suite: 42/42, typecheck, and production build.
- Weekend v10 pinned Radeon source: 33/33 and production build.
- vLLM graph serving reached 257.65 aggregate output tokens/s at concurrency
  eight versus 20.66 for the serialized Transformers server.
- Native Qwen3-ASR batch-eight reached 85.35x aggregate real-time and was
  6.66x faster than sequential inference.
- Voice Evidence v0.3 closes a measured burst-loss blind spot and forces old
  v0.2 proofs through revalidation.

## Evidence Boundary

- Main Demo V2 is the real Cloudflare + W7900 inference and performance proof.
- Continuous Demo V2 uses deterministic ASR/compiler fixtures with real Node
  process restarts; it proves lifecycle control, not GPU throughput.
- Quark INT4 W4A16 export reduced storage by 66.73%, but the installed vLLM
  Quark loader rejected that weight-only serving scheme.
- Quark INT8 W8A8 reduced model-load VRAM by 44.07% and increased KV-cache
  capacity by 88.43%, but was 36.70% slower at concurrency eight.
- INT8 C128 passed only 11/51 complete safety-semantic gates and 2/51 strict
  JSON checks; FP16 passed 51/51. INT8 is rejected for the policy compiler.
- Adaptive Precision Controller v12 added JSON Schema, semantic admission, and
  FP16 fallback. Schema INT8 remained 0/12 admitted; fallback restored 12/12.
- A real audio-backed proof records `selected = fallback`, preserves
  `mail.send = deny`, and passes 7/7.
