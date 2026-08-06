# AMD AI DevMaster 2026 — Track 2 Submission Checklist

Official submission language: **English**.

## Required Materials

- [x] Project Specification Document
  - `submission/PROJECT_SPECIFICATION.md`
  - Covers application scenario, architecture, core capabilities, model,
    deployment, AMD optimization, and verification.
- [x] Chinese companion specification
  - `submission/PROJECT_SPECIFICATION_CN.md`
  - Supplementary only; English remains the official submission language.
- [x] Complete Project Source Code
  - Main source tree is present in this repository.
  - Local AMD provider and health endpoint are implemented.
- [x] Repository README finalized
  - Radeon local-provider quick start added.
  - Provider list, tool count, model, and environment variables updated.
- [x] Live narrated Demo Video, 1:14 at 1920 x 1080
  - `demo-video/final/solo-worker-os-live-radeon-demo-2026-08-06-en-vo.webm`
  - Shows live `create_project` and `generate_contract` tool calls.
  - Includes an English voiceover synchronized to the recorded UI.
  - Companion evidence links the run to Radeon, ROCm, vLLM, and HTTP 200 logs.
  - Extended 3:09 evidence-based WebM remains available as a fallback.
- [x] Supplementary Poster
  - `submission/poster/solo-worker-os-poster-v2.html`
  - Uses only verified GPU facts and real screenshots.
- [x] Poster exported to PNG for convenient review.
  - `submission/poster/solo-worker-os-poster-v2.png`
- [ ] Optional: export the poster to PDF.
- [ ] Fork the official repository and open a Pull Request.
- [x] Pull Request description prepared.
  - `submission/PR_DESCRIPTION.md`

## Pull Request Format

Use the title format required by the official repository:

```text
Track 2, <Team Name or Participant Name>, Solo Worker OS
```

The Pull Request description should link to:

- Project specification.
- Reproduction instructions.
- Demo video.
- Poster.
- GPU evidence index.

## Verified AMD Evidence

- [x] Radeon instance and ROCm image.
- [x] AMD/ATI device output from `rocm-smi`.
- [x] VRAM allocation while Qwen3-4B was loaded.
- [x] Active vLLM and EngineCore processes.
- [x] Served-model response from `/v1/models`.
- [x] Successful `/v1/chat/completions` HTTP 200 logs.
- [x] Solo local-provider health response.
- [x] End-to-end `create_project` tool execution.
- [x] End-to-end `generate_contract` tool execution.

Evidence index: `docs/evidence/README.md`.

## Claims Review

- Do not claim that the recorded Radeon Cloud configuration keeps data on the
  participant's physical device.
- Use: "participant-controlled, self-hosted AMD Radeon GPU inference endpoint."
- Do not claim measured tokens per second until a reproducible benchmark has
  completed.
- Use Qwen3-4B and ROCm 7.2.1 consistently across all materials.
- Do not include temporary tunnel URLs, access tokens, private keys, or account
  email addresses in submission files.
