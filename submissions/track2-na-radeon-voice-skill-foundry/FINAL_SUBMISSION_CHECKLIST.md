# Final Submission Checklist

Deadline: 2026-08-06 23:59 UTC+8.

## Eligibility

- [x] Luma registration approved
- [x] AMD Developer Program registered
- [x] Radeon Cloud credits available
- [x] Solo entry; PR team name must be `N/A`
- [x] GitHub ID: `Chengyuann`
- [x] Discord/WeChat joined

## Track 2 Technical Requirements

- [x] Core Agent inference on AMD Radeon + ROCm
- [x] Local ASR on AMD Radeon + ROCm
- [x] Local RAG
- [x] Tool invocation
- [x] Multi-step planning
- [x] Local multi-turn/procedural memory
- [x] Permission and privacy controls
- [x] Targeted Radeon inference optimization
- [x] Raw benchmark evidence committed

## Required Deliverables

- [x] Complete public source repository
- [x] English README with setup and dependencies
- [x] English Project Specification Markdown
- [x] English Project Specification PDF
- [x] Agent architecture diagram
- [x] Supplementary poster
- [x] 3-5 minute English demo script
- [x] Record final demo video
- [x] Upload demo video and verify public access
- [x] Add video URL to `submission/README.md`
- [x] Add video URL to official submission PR body

## Quality Gates

- [x] Local `npm test`: 21/21 passed
- [x] Local `npm run build`: passed
- [x] Radeon baseline `npm test`: 10/10 passed
- [x] Re-run the 21-test suite on Radeon after Voice Evidence Gate sync
- [x] Radeon `npm run build`: passed
- [x] Agent service health: passed
- [x] ASR service health: passed
- [x] Local Voice Evidence Gate fixture: 100/100 pass
- [x] App service health: passed
- [x] Compact-output semantic gate: passed in 3/3 runs
- [x] `mail.send = deny`
- [x] Original Radeon workflow fixtures: 6/6 passed
- [x] Local audio-backed verification: 7/7 fixtures passed
- [x] Re-run audio-backed verification on Radeon: 7/7 fixtures
- [x] Radeon v9 lifecycle enhancement suite: 29/29 passed
- [x] Radeon v9 production build: passed
- [x] Benchmark JSON validates
- [x] Proof ZIP integrity validates
- [x] Secret scan passed

## Official Repository Submission

- [x] Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`
- [x] Create submission branch
- [x] Add `submissions/track2-na-radeon-voice-skill-foundry/`
- [x] Include submission index and required materials
- [x] Open English PR
- [x] PR title:
  `Track 2, N/A, Radeon Voice Skill Foundry`
- [x] Verify all links from an incognito browser

Official PR:
`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`

## Evidence Values

- Final Radeon validation commit:
  `c759a417c68d06f639e3df797f50b4ebd7b81091`
- Original Radeon proof ZIP SHA-256:
  `0f9a37f69aea24677561b3c43c2e5fbfa275aa0fadf0509816a7a8f1229879bd`
- Local audio-backed proof ZIP SHA-256:
  `8c68e2b2c1dc6fec4f73601488113241259d751a82e0e5e2ab65f1f001911f30`
- Radeon audio-backed proof ZIP SHA-256:
  `6ea53dfe28f8221b3db9b06e6eed537767bf28b4c6536d25d45f3ffec20500e9`
- Radeon audio-backed proof hash:
  `6ff30ccc2d052e226051fa6819760abe3b2c2ef6243b63169ab9d5e0caebfc40`
- Demo video SHA-256:
  `36a76facf388ea65e61470da418eb2c9b507120b89a496a1b557be162d0c73ff`
- Demo captions SHA-256:
  `f884f85e8c8974b9e3cf5e40871d83b4586ebd72daa92c4ee5d2c5cbdae9a6fb`
- Video cover SHA-256:
  `7929ee19046c6c816452ea6a68493a52a1a95b7da4dc0f75e384523a1e03d940`
- Promo banner SHA-256:
  `54374903cac3bf6791bdfd16c918e1afb06f6c75a7de9e8d6b3dae59875cf615`
- Social card SHA-256:
  `d058bdb46ef3b808b238e5811a21e0881865b704dc8b1db71b68dfc7d9398484`
- Demo TTS:
  `gemini-3.1-flash-tts-preview`, male voice `Charon`
- Continuous operation demo SHA-256:
  `b86585ee7cbd2655530a9445dff438998ccc8a6e6d451c8462b53cb680fc2a68`
- Continuous operation captions SHA-256:
  `b0e5692855f88d08406f9131387d81522a084b86a66f15849ff3f84e2b359bab`
- Continuous lifecycle proof ZIP SHA-256:
  `25b18d367a212b3a0986dc62fbf7112f1b22e6b8ace9a8ca3086044ba8bc1d8e`
- Video caption delivery:
  burned-in English narration captions plus embedded English subtitle tracks
- Voice Evidence v0.2 lifecycle proof hash:
  `0c175843082b4464094f578c00598e8ec1b416ccbf5f7855c0e4d65e9deb5edf`
- Lifecycle enhancement validation commit:
  `efec128059fea3b68521aa1dd333c71d5ea6a679`
- Optimization JSON SHA-256:
  `ce2848f92c7f93b30fe558c99128cb6eba1988319931f7ab0bdcc803d291298d`
- W7900-class GPU: `gfx1100`, 47.98 GiB VRAM
- ROCm: 7.2.1
- Agent median TTFT: 108.87 ms
- Agent median throughput: 22.02 tokens/s
- ASR warm median RTF: 0.0556
- Final SOP ASR RTF: 0.0699, 14.3x real-time
- Final Agent compile: 24.13 s, 368.16 ms TTFT, 20.07 tokens/s
- Output token reduction: 29.42%
- Generation latency reduction: 30.03%
- Exact reuse HTTP median: 2.18 ms
- Measured exact-reuse speedup: 11,052.03x

## Weekend W7900 v10 Evidence

- [x] Transformers versus vLLM eager versus vLLM graph
- [x] Heterogeneous prompt concurrency 1/2/4/8, three bursts each
- [x] Context-length TTFT and throughput comparison
- [x] Per-second GPU utilization, VRAM, temperature, and power telemetry
- [x] Qwen3-ASR native batch 1/2/4/8 versus sequential
- [x] Noise, reverb, far-field, clipping, and burst-loss voice evidence
- [x] Voice Evidence v0.3 burst-loss fix validated on W7900
- [x] Local 33/33 tests and production build
- [x] Radeon 33/33 tests and production build
- vLLM graph concurrency-eight aggregate throughput: `257.65 tokens/s`
- Transformers concurrency-eight aggregate throughput: `20.66 tokens/s`
- serving throughput improvement: `12.47x`
- Qwen3-ASR batch-eight aggregate speed: `85.35x real-time`
- Qwen3-ASR batch-eight speedup over sequential: `6.659x`
- Voice Evidence v0.3:
  clean `pass / 100`, 120 ms burst loss `review / 88`,
  280 ms burst loss `quarantine / 65`
- Machine-readable summary:
  `benchmarks/weekend-v10-summary.json`
- Weekend v10 summary SHA-256:
  `4871e76d1d0204c5d0179418132ed778f53b8adc6a230120d2974ff61be7158a`
- Weekend v10 evidence ZIP SHA-256:
  `1189e0e47c14ba18784f5be82aa5c68366946c0d6378d6a8d26adef61dfd3e9b`
- Weekend v10 implementation commit:
  `20776d980ebd4ec8daf6e6b909da4a2933a36dfa`
- Technical report:
  `docs/WEEKEND_W7900_EXPERIMENTS.md`
