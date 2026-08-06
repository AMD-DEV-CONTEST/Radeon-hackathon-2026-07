# ProofLaunch Radeon / ROCm evidence index

This index separates observed execution from environment proof, deployment
proof and unexecuted contracts. It prevents an uploaded Notebook or configured
route from being misrepresented as a completed end-to-end Radeon run.

## Tier A — observed historical Radeon model execution

The strongest preserved evidence is the executed Notebook
[`gemma4_emotion_lora_modelscope_single_gpu_original.ipynb`](../notebooks/gemma4_emotion_lora_modelscope_single_gpu_original.ipynb),
bound by SHA-256 in
[`RADEON_GEMMA4_EXECUTION_RECEIPT_2026-08-06.json`](RADEON_GEMMA4_EXECUTION_RECEIPT_2026-08-06.json).

Its saved outputs observe:

- PyTorch `2.10.0+git8514f05`, one `AMD Radeon Graphics` device and HIP
  `7.2.53211`;
- `google/gemma-4-E4B-it` loaded on `cuda:0` using `bfloat16`;
- deterministic Gemma-4 generation returning `joy` for a positive-emotion
  input;
- a 400-example pre-training evaluation (`accuracy=0.625`,
  `macro_f1=0.4824237718715574`);
- a 250-step LoRA run lasting 702.3645 seconds with training loss
  `0.3145033791065216`, followed by adapter save output.

The Notebook does not embed an execution timestamp, per-inference latency or
peak VRAM. Its post-training evaluation did not finish. It demonstrates a real
historical Gemma-4 model path on Radeon/ROCm, not a fresh end-to-end ProofLaunch
campaign run.

## Tier B — observed AMD platform and hardware capability

- [`RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json`](RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json)
  records an executed official template output with one `AMD Radeon Graphics`
  device on `cuda:0`. It does not prove multi-GPU or a fresh project run.
- [`RADEON_BROWSER_SESSION_2026-07-29.json`](RADEON_BROWSER_SESSION_2026-07-29.json)
  and [`RADEON_BROWSER_SESSION_V10.json`](RADEON_BROWSER_SESSION_V10.json)
  bind the uploaded ProofLaunch archives and Notebooks to exact hashes on the
  AMD instance.
- [`RADEON_BROWSER_SYNC_2026-07-30.json`](RADEON_BROWSER_SYNC_2026-07-30.json)
  records browser upload state while explicitly withholding remote byte parity
  where readback was unavailable.

## Tier C — observed execution-plane blocker

- [`RADEON_RUNTIME_ROUTE_AUDIT_2026-07-29.json`](RADEON_RUNTIME_ROUTE_AUDIT_2026-07-29.json)
  shows that the official client depends on the standard Jupyter WebSocket
  execution route.
- [`v10/radeon-instance-recovery-2026-07-31.json`](v10/radeon-instance-recovery-2026-07-31.json),
  [`v10/radeon-runtime-reprobe-2026-07-31.json`](v10/radeon-runtime-reprobe-2026-07-31.json)
  and [`v10/radeon-template-ab-reprobe-2026-07-31.json`](v10/radeon-template-ab-reprobe-2026-07-31.json)
  record healthy authenticated REST reads but HTTP 403 on kernel/event
  WebSockets before Python or ROCm code could execute.

These records explain why the newer ProofLaunch V10 archive was uploaded and
verified but not freshly executed.

## Claims that remain open

- fresh end-to-end ProofLaunch GTM execution on Radeon;
- Radeon image and video generation in the submitted workflow;
- per-stage latency, peak VRAM and GPU-utilization capture;
- final campaign-output hashes produced in the same fresh Radeon run;
- multi-GPU/RCCL stability, equivalence or speedup.

The 190.9-second product Demo Video shows the real product workflow and output
surfaces. It does not show the historical Notebook run and is not used as a
substitute for the open end-to-end Radeon capture.
