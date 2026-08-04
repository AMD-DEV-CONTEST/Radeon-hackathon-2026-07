# Radeon Cloud session 2 plan

> Completed on 2026-07-25 with a partial acceptance result. The authenticated
> FastAPI-to-ROCm job, output persistence, and API review round-trip passed.
> Browser-to-cloud acceptance was blocked by the missing `rc-tunnel` command
> and an unavailable verified fallback endpoint. See
> [radeon-session-2-results.md](radeon-session-2-results.md).

## Objective

Validate one complete rights-safe browser → authenticated FastAPI → single GPU
worker → SDXL img2img → browser review flow. Use exactly one
`BrandPilot-Track1` instance with Persistent PVC.

## Hard timing controls

- Record starting balance and prove no active instance before launch.
- Record launch and ready timestamps.
- Target 30–40 minutes; hard maximum 45 minutes from ready.
- Begin shutdown preparation by minute 35.
- Stop browser polling and the temporary tunnel by minute 38.
- Stop FastAPI, unset the temporary token, and destroy by minute 42.
- Verify **No active instance** and record final displayed balance by minute 45.
- Never launch a second instance.

## Cloud preparation

Use `/opt/venv/bin/python`, never `/usr/bin/python`. Verify PyTorch/HIP/device,
Persistent PVC, model cache, output directory, and installed user-space
packages before installing anything. Do not install or replace PyTorch, CUDA,
NVIDIA wheels, xformers, bitsandbytes, or system packages.

Update the exact pushed `fastapi-rocm-integration` source. If GitHub TLS
verification fails, do not weaken TLS. Upload a SHA-256-verified `git archive`
of the pushed commit through authenticated JupyterLab and re-hash it on the
PVC.

Generate a new `secrets.token_urlsafe(32)` token in memory for this session.
Do not print, persist, screenshot, or commit it. Start FastAPI on
`127.0.0.1:8000` with experimental mode and demo authentication enabled, the
validated model/revision, persistent cache/output roots, and the local
frontend CORS origins.

Verify locally in the cloud:

- unauthorized status returns 401
- authorized status confirms AMD GPU, HIP, model, and revision
- model remains unloaded before first generation
- only the API loopback port is exposed by the official temporary tunnel
- unauthorized tunnel access returns 401

## End-to-end acceptance

From the local browser:

1. Connect with the runtime URL and ephemeral access code.
2. Confirm AMD device, ROCm, model, revision, and experimental mode.
3. Create a rights-safe example project and upload the repository example.
4. Submit one selected style and one output format.
5. Observe real states and any real diffusion steps.
6. Verify a duplicate active submission is blocked.
7. Retrieve and render the real output and measured metadata.
8. Record approved, rejected, or needs-changes human review.
9. Refresh the project view and verify persistence.

A warm second job is optional only after full success with at least 12 minutes
remaining. It must not threaten shutdown.

## Evidence

Save only sanitized status, completed job metadata, generated output, browser
result/disclosure, redacted backend log, GPU activity, and final no-active proof
under `evidence/radeon-session-2/`. Exclude the token, tunnel URL, environment,
emails, account/instance IDs, internal hosts, browser state, cache, and weights.
