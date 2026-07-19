# Radeon Voice Skill Foundry

**Track 2 | Team N/A | Solo entry**

**Speak the SOP. Prove the Skill.**

Radeon Voice Skill Foundry turns a private spoken SOP and an aligned action
trace into a verified, reusable Agent Skill before risky actions are permitted.

## Links

- Source repository:
  https://github.com/Chengyuann/radeon-voice-skill-foundry
- Live interactive demo:
  https://radeon-voice-skill-foundry.pages.dev/
- Recommended live Demo V2, 4 minutes 49 seconds:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.mp4
- Demo V2 captions:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V2.srt
- Demo V2 proof:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/demo-v2-proof.zip
- Original overview video:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4
- Continuous operation demo, 3 minutes 10 seconds:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/CONTINUOUS_OPERATION_DEMO.mp4
- Continuous lifecycle proof:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/continuous-demo-proof.zip
- Final Radeon proof ZIP:
  https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/radeon-audio-proof-v8.zip
- License: MIT

Demo V2 contains burned-in English narration captions and an embedded English
subtitle track. Narration uses AIDP `gemini-3.1-flash-tts-preview`, male voice
`Charon`.

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

## Lifecycle Engineering Upgrade

Public enhancement commit:
`efec128059fea3b68521aa1dd333c71d5ea6a679`.

- Voice Evidence v0.2 adds estimated SNR, noise floor, speech level, crest
  factor, DC offset, short dropout, and channel imbalance diagnostics.
- Voice evidence, trusted compile runs, and verification results persist
  atomically across service restart.
- Proof compatibility binds verifier version, runtime, tools, policy, skill,
  and voice-evidence schema.
- A changed runtime marks a skill `revalidation_required` and blocks reuse.
- One-click revalidation creates a new child run, reruns 7/7 fixtures, and
  restores proof compatibility.
- Clean Radeon Cloud v9 clone: `npm ci`, 29/29 tests, and production build
  passed on ROCm 7.2.1 / `gfx1100` / 51,522,830,336-byte VRAM.

The single-take continuous demo records upload, v0.2 analysis, compile,
verification, save, reuse, two real service restarts, proof invalidation,
revalidation, and proof download in one browser session.

## Public Full-Stack Demo

The Cloudflare Pages deployment keeps browser requests same-origin under
`/api`, injects a server-held gateway token, and forwards only authenticated
requests to the W7900 runtime. The public flow was re-run end to end on commit
`12dbec1`:

- Qwen3-ASR processed the 20.39-second Chinese SOP on Radeon
- Voice Evidence v0.3 passed at 100/100
- Chinese `不要自动发送` produced `mail.send = deny`
- Qwen3-4B produced 13 constraints with measured Radeon metrics
- deterministic verification passed 7/7 and issued four receipts
- the verified skill was saved and reused
- the proof ZIP downloaded and passed archive integrity validation

The current account has no Cloudflare-managed DNS zone, so the W7900 origin
uses an authenticated Quick Tunnel. Pages remains stable, but a GPU/Tunnel
restart requires rotating the encrypted `RADEON_API_ORIGIN` Pages secret.

Demo V2 records this public path without cached policy substitution or
accelerated model footage. The final MP4 is 4:48.64 at 1920x1080, with visible
Voice Evidence v0.3, Chinese no-send enforcement, seven generated fixtures,
7/7 proof, four receipts, Memory reuse, and the W7900 vLLM/ASR batching
evidence.

## Submission Files

- `PROJECT_SPECIFICATION.pdf`: required English specification
- `PROJECT_SPECIFICATION.md`: accessible source version
- `ARCHITECTURE.png`: Agent architecture
- `POSTER.pdf` and `POSTER.png`: supplementary poster
- `VIDEO_COVER_V2.png`: cinematic video cover
- `PROMO_BANNER_V2.png`: campaign banner
- `SOCIAL_CARD_V2.png`: square social campaign card
- `RADEON_AUDIO_PROOF_V8.json`: raw final validation summary
- `DEMO_SCRIPT.md`: narration and shot list
- `CONTINUOUS_OPERATION_DEMO.srt`: continuous demo captions
- `CONTINUOUS_DEMO_NARRATION.md`: continuous demo narration
- `LIFECYCLE_ENHANCEMENTS_V9.json`: machine-readable enhancement evidence

## Disclosure

- The Chinese SOP WAV is a reproducible synthetic fixture, not a human
  recording.
- Demo narration is AI-generated.
- Final narration uses AIDP `gemini-3.1-flash-tts-preview`, voice `Kore`.
- Campaign backgrounds were generated with GPT Image 2; visible text and
  measured metrics were composed locally.
- Product UI footage in the demo is labeled as deterministic replay footage.
- Radeon runtime screenshots, metrics, proof hashes, and the final proof ZIP
  come from the actual Radeon Cloud validation.
