# Radeon Voice Skill Foundry

**Track 2 | Team N/A | Solo entry**

**Speak the SOP. Prove the Skill.**

Radeon Voice Skill Foundry turns a private spoken SOP and an aligned action
trace into a verified, reusable Agent Skill before risky actions are permitted.

## Links

- Source repository:
  https://github.com/Chengyuann/radeon-voice-skill-foundry
- Demo video, 3 minutes 40 seconds:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4
- Demo captions:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt
- Final Radeon proof ZIP:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/radeon-audio-proof-v8.zip
- License: MIT

## Why Voice Is Structural

Action traces capture what an expert did. Voice captures why, when, exceptions,
privacy boundaries, and what must never happen.

The system compiles both signals into:

- typed SOP constraints
- local RAG evidence
- least-privilege capability policy
- positive and adversarial fixtures
- deterministic verification
- governance receipts
- a hash-bound proof bundle
- versioned procedural memory for exact Verified Skill reuse

## Radeon Runtime

Final validation used source commit
`c759a417c68d06f639e3df797f50b4ebd7b81091`.

| Component | Measured configuration |
|---|---|
| GPU | AMD Radeon Pro W7900-class, `gfx1100`, 47.98 GiB VRAM |
| ROCm | 7.2.1 |
| Agent | Qwen3-4B-Instruct-2507, Transformers FP16 |
| ASR | Qwen3-ASR-0.6B, Transformers FP16 |
| Tests | 21/21 passed on Radeon Cloud |
| Production build | passed on Radeon Cloud |

Final 20.39-second audio-backed rerun:

| Metric | Result |
|---|---:|
| Voice Evidence Gate | 100/100 |
| ASR inference | 1.4259 s |
| ASR RTF | 0.0699 |
| ASR speed | 14.3x real-time |
| Agent compile duration | 24.1331 s |
| Agent TTFT | 368.16 ms |
| Agent throughput | 20.07 tokens/s |
| Agent peak VRAM | 8.001 GiB |
| Generated constraints | 13 |
| Verification | 7/7 fixtures passed |
| Final permission | `mail.send = deny` |
| BLOCK receipts | 3 |

The verification request deliberately changed the client-side `mail.send`
permission to `allow` and supplied a fake action trace. The server ignored
those untrusted fields, resolved the authoritative compile run, and still
returned `mail.send = deny` with 7/7 fixtures.

## Radeon Optimization

On the same allocation:

- compact structured output reduced median model output by 29.42%
- compact structured output reduced median generation latency by 30.03%
- the semantic safety gate remained satisfied in 3/3 compact runs
- exact Verified Skill reuse measured 2.18 ms median HTTP round-trip versus
  24.09 s for the measured full compilation, an 11,052x fast path

The reuse number applies to an identical already-verified skill lookup, not to
arbitrary changed workloads.

## Submission Files

- `PROJECT_SPECIFICATION.pdf`: required English specification
- `PROJECT_SPECIFICATION.md`: accessible source version
- `ARCHITECTURE.png`: Agent architecture
- `POSTER.pdf` and `POSTER.png`: supplementary poster
- `RADEON_AUDIO_PROOF_V8.json`: raw final validation summary
- `DEMO_SCRIPT.md`: narration and shot list

## Disclosure

- The Chinese SOP WAV is a reproducible synthetic fixture, not a human
  recording.
- Demo narration is AI-generated.
- Product UI footage in the demo is labeled as deterministic replay footage.
- Radeon runtime screenshots, metrics, proof hashes, and the final proof ZIP
  come from the actual Radeon Cloud validation.
