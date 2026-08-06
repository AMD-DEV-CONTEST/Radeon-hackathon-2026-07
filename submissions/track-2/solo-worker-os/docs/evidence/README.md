# AMD GPU Evidence Index

Captured on 2026-08-06 (Asia/Shanghai). The Radeon instance reports UTC; for
example, `2026-08-05T18:39:33+00:00` is `2026-08-06 02:39:33+08:00`.

## Submission-ready screenshots

1. `00-radeon-instance-details.png`
   - Radeon Cloud instance `u-14615-b0cebd0b`
   - One GPU and the ROCm 7.2.1 / vLLM 0.16.0 image
2. `01-rocm-vllm-terminal.png`
   - ROCm detects an AMD/ATI GPU and reports 51% VRAM allocation
   - `Qwen/Qwen3-4B` is running under `vllm serve`
   - `/v1/models` serves the same model
   - Multiple `/v1/chat/completions` requests return HTTP 200
3. `03-solo-local-llm-create-project.png`
   - A Chinese natural-language request invokes `create_project`
4. `04-solo-local-llm-generate-contract.png`
   - A follow-up request invokes `generate_contract`
5. `05-rocm-vllm-after-product-response.png`
   - A fresh timestamp after the product interactions
   - ROCm, the active vLLM process, the served model, and new HTTP 200 requests
     appear together

## Recommended evidence sequence

Use screenshots 00, 03, 04, and 05 in the submission. Screenshot 01 is the
strongest terminal-level backup because it shows the AMD device, model process,
served-model response, and successful inference requests in one frame.

The original local-provider status capture is intentionally excluded from Git:
it contains a retired temporary tunnel hostname. The tunnel was stopped after
capture, but endpoint identifiers are unnecessary in a public submission.

## Shutdown record

At `2026-08-05T18:43:42+00:00` (`2026-08-06 02:43:42+08:00`):

- The temporary public tunnel was stopped.
- The vLLM and EngineCore processes were stopped.
- Port 8000 rejected connections after shutdown.
- The local Next.js process was stopped; port 3000 no longer listened.
- The Radeon instance was not destroyed.

Radeon Cloud exposes no pause/stop operation for this account. Its UI only
offers **Destroy Instance**, so the instance remains available for a later
session even though the application services and public connection are closed.
