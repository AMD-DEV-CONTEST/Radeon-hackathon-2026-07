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
- Demo video:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
- Demo captions:
  `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt`
- Official submission PR:
  `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`
- Continuous operation demo:
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
- `ARCHITECTURE.png` - Agent architecture diagram
- `POSTER.pdf` - supplementary one-page poster
- `POSTER.png` - poster preview
- `VIDEO_COVER_V2.png` - cinematic 16:9 video cover
- `PROMO_BANNER_V2.png` - 16:9 campaign banner
- `SOCIAL_CARD_V2.png` - square social campaign card
- `DEMO_SCRIPT.md` - 3-5 minute English demo narration and shot list
- `DEMO_NARRATION.md` - final AI-generated English voiceover text
- `RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt` - final captions
- `CONTINUOUS_OPERATION_DEMO.srt` - continuous workflow captions
- `CONTINUOUS_DEMO_NARRATION.md` - continuous workflow narration source
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

Raw measurements are in:

- `benchmarks/w7900-2026-07-17.json`
- `benchmarks/optimization-w7900-2026-07-17.json`
- `benchmarks/radeon-audio-proof-v8-2026-07-18.json`
- `benchmarks/lifecycle-enhancements-v9-2026-07-18.json`

## Current External Deliverable Status

- Source repository: complete
- English specification: complete
- Architecture diagram: complete
- Poster: complete
- Demo script: complete
- Demo video URL: complete
- Official hackathon PR: open and publicly verified

The final narration uses AIDP `gemini-3.1-flash-tts-preview`, voice `Kore`.
Visual campaign backgrounds were generated with AIDP GPT Image 2; all visible
project typography and measured values were composed locally.

## Post-Submission Engineering Upgrade

- Voice Evidence v0.2 adds estimated SNR, noise floor, speech level, crest
  factor, DC offset, short dropout, and channel imbalance diagnostics.
- Server-authoritative evidence, compile runs, and verification results persist
  across service restart.
- Every proof carries a compatibility manifest for verifier, runtime, tools,
  policy, skill, and voice-evidence schema.
- Changed runtime identity marks a skill `revalidation_required`; one-click
  revalidation creates a new child run before reuse is restored.
- Local enhanced regression suite: 29/29 passed.
