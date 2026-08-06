# AMD Radeon Live Demo Evidence - 2026-08-06

This package records a live, end-to-end Solo Worker OS run backed by the
participant's dedicated Radeon Cloud instance. The temporary public endpoint
used during recording is intentionally omitted and was stopped after capture.

## Runtime

- Radeon Cloud instance: `u-14615-b0cebd0b`
- Template: `Solo Worker OS Debug`
- GPU vendor: `Advanced Micro Devices, Inc. [AMD/ATI]`
- ROCm architecture: `gfx1100`
- Inference server: vLLM `0.16.1.dev0`
- Served model: `Qwen/Qwen3-4B`
- Maximum model context: 4096 tokens
- Solo Worker OS provider: `local`

## Live Recording

File: `demo-video/final/solo-worker-os-live-radeon-demo-2026-08-06.webm`

- Resolution: 1920 x 1080
- Duration: 74.56 seconds
- Size: 5,919,156 bytes
- SHA-256: `BA5418B42D76B4F8506B2F30046095D4E121533CC672A8BE5C4242C02A9BF3E4`

Primary narrated file:
`demo-video/final/solo-worker-os-live-radeon-demo-2026-08-06-en-vo.webm`

- English voiceover: Microsoft Zira Desktop
- Resolution: 1920 x 1080
- Duration: 74.56 seconds
- Tracks: 1 video, 1 audio
- Size: 17,329,023 bytes
- SHA-256: `CACE0815BB56B006DAFD672A9EB6729A9F16240D666F4B243E5D69C19AE7B929`

The narration source and timed WAV are stored in `demo-video/VOICEOVER_EN.md`
and `demo-video/final/audio/`. The timed WAV SHA-256 is
`18765608CA193A0B88095A45960F5FEAD55BF5F0E67CF6290DBDE89455BC4FD5`.

Key moments:

- `00:18`: sanitized `/api/local-llm/status` response shows `provider: local`,
  `reachable: true`, and `Qwen/Qwen3-4B`.
- `00:35`: the live agent calls `create_project` and creates a CNY 12,800
  website project for Lin Yue.
- `00:44`: the next turn calls `generate_contract` and displays the complete
  service agreement derived from the new project.
- `00:54`: the execution trace view shows the recorded agent runs.
- `01:07`: the Projects view shows the newly persisted project.

## GPU and Request Proof

`docs/evidence/amd-radeon-live-gpu-2026-08-06.png` was captured from the
instance's authenticated Jupyter terminal immediately after recording. It
shows all of the following in one frame:

- Radeon GPU vendor and `gfx1100` architecture reported by `rocm-smi`.
- 51% VRAM allocated by the loaded model.
- The live `vllm serve Qwen/Qwen3-4B` process.
- `/v1/models` reporting `owned_by=vllm` and `max_model_len=4096`.
- Six successful `POST /v1/chat/completions HTTP/1.1 200 OK` requests from the
  recording session.

The instantaneous GPU utilization is 0% in the post-run screenshot because
the requests had completed. The allocated VRAM, live vLLM process, served
model response, and request log establish the complete inference chain.

GPU screenshot SHA-256:
`EBE8C121C516A9B0E112A971851DABD88093C1A37A71430AFDD6AFABADFC5773`

Additional extracted frames:

- `docs/evidence/live-demo-create-project.png`
- `docs/evidence/live-demo-generate-contract.png`
- `docs/evidence/live-demo-trace.png`
- `docs/evidence/live-demo-project-result.png`

## Reproduction

The recording automation is stored at
`demo-video/record_live_radeon_demo.mjs`. It launches a 1920 x 1080 browser,
checks the live local-model status, sends both prompts through the product UI,
waits for each streamed response to finish, and records the trace and persisted
project result. No prerecorded chat response is injected into the application.
