# Track 2 - KoushiKo Vault

**Participant:** Haruto Watanabe (individual submission)<br>
**Application:** KoushiKo Vault - Private Agentic Evidence Investigator for Time-Coded Media Archives<br>
**Source release:** [`track2-submission-2026-08-05`](https://github.com/Yasei-no-otoko/koushiko-vault/tree/track2-submission-2026-08-05) at commit [`810cb333a76cfda232dd9dd03484d98f90b359fd`](https://github.com/Yasei-no-otoko/koushiko-vault/commit/810cb333a76cfda232dd9dd03484d98f90b359fd)

## What it does

KoushiKo Vault is a local-first evidence-investigation agent for confidential documents and time-coded media. A reviewer can ask a question about a private archive and receive an inspectable investigation plan, grounded findings with exact document pages and video timecodes, a seekable evidence timeline, a generated evidence reel, and a self-contained HTML report. Case data and model inference remain on the local machine.

The reproducible public demo uses an original synthetic factory-safety case. It asks the agent to identify every moment that conflicts with policy Section 4.2, separate confirmed evidence from uncertainty and resolved conflicts, and create a 45-second evidence reel.

## Submission materials

| Track 2 deliverable | Immutable artifact |
| --- | --- |
| Project specification | [8-page PDF](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/KoushiKo_Vault_Project_Specification.pdf) |
| Complete source code | [Tagged source tree](https://github.com/Yasei-no-otoko/koushiko-vault/tree/track2-submission-2026-08-05) |
| Environment, dependencies, startup, and reproduction | [English README](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/README.md) |
| Real demo video | [4:18, 1080p H.264/AAC MP4](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/KoushiKo_Vault_Track2_Demo.mp4) |
| Supplementary deck | [Editable PPTX](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/KoushiKo_Vault_Track2_Deck.pptx) and [8-page PDF](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/KoushiKo_Vault_Track2_Deck.pdf) |
| Checksums and media metadata | [Submission manifest](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/manifest.json) |
| Package index and traceability | [Submission README](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/submission/SUBMISSION_README.md) and [rules traceability](https://github.com/Yasei-no-otoko/koushiko-vault/blob/track2-submission-2026-08-05/docs/RULES_TRACEABILITY.md) |

## Local AMD Radeon implementation

- Host: AMD Ryzen AI Max+ 395 with Radeon 8060S graphics (`gfx1151`).
- Runtime: ROCm 7.2 and ROCmFPX HIP commit `b41ce12ea698b3a6cf2e83e31f582c576129c660`.
- Model: pinned Qwen3.6-35B-A3B ROCmFP4 STRIX_LEAN GGUF; exact source revision, size, license, and SHA-256 are in `config/model-manifest.json`. Model weights are not committed.
- Serving: OpenAI-compatible loopback endpoint on `127.0.0.1:8138`, full Radeon offload (`ROCm0`, 999 requested GPU layers), Flash Attention enabled, 8K context, batch/micro-batch 512/512, and 32 CPU threads.
- Measured three-run medians on the pinned workload: CPU-only 20.352 prompt tokens/s and 1.447 generation tokens/s; Radeon full offload 1,035.830 prompt tokens/s and 67.813 generation tokens/s. This is a 50.90x prompt and 46.86x generation median ratio on this machine and workload. Raw samples, ranges, commands, stdout, and stderr are retained in the source release.

## Agent and validation evidence

- Bounded understand-plan-tool-evidence-verify loop with typed tools, step/time limits, cancellation, and no arbitrary command execution.
- SQLite FTS5 retrieval with page, section, character-range, and transcript-timecode provenance.
- Citation verifier rejects invalid sources, pages, timecodes, quotes, and unsupported claims.
- Latest retained API investigation: 12.659 seconds, 11 evidence records, verified citations, a playable 45.0-second reel, and an HTML report.
- Required live-browser API/SSE gate: passed in 20.676 seconds, including citation seek, reel/report export, pre-response cancellation race, and zero browser-console errors.
- Validation: 12 core Python tests, 6 release-artifact Python tests, 6 frontend tests, production build, ROCmFPX 1,776/1,776 backend operations, and 22/22 environment preflight checks passed.
- The recorded run used the local model for planning. Final synthesis used the disclosed deterministic verified fallback; this entry does not claim model-only final synthesis for that run.

## Reproduce the validated path

```powershell
git clone https://github.com/Yasei-no-otoko/koushiko-vault.git
Set-Location koushiko-vault
git checkout track2-submission-2026-08-05
./scripts/preflight.ps1
./scripts/setup.ps1 -BuildJobs 32
./scripts/start.ps1
./scripts/demo.ps1
./scripts/verify-offline.ps1 -ActiveApiProbe -VerifySourceGuards
./scripts/test.ps1 -RequireLiveE2E
./scripts/stop.ps1
```

## Platform disclosure

The formal Rules & Conditions contain wording that can be read as requiring an AMD Radeon GPU in Radeon Cloud with ROCm, while the official repository emphasizes actual Radeon execution and the same rubric separately describes an optional Radeon Cloud model-API bonus. This entry reports only measured local Ryzen AI Max+ 395 / Radeon 8060S ROCm execution. It does **not** claim Radeon Cloud execution or the optional Radeon Cloud API bonus. The limitation is disclosed for organizer review.

All public case data and media are original synthetic materials. The application is MIT-licensed; model, runtime, dependency, and synthetic-dataset licenses are documented in the tagged source release.
