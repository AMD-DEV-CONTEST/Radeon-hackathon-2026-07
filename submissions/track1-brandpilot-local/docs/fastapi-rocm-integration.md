# Experimental FastAPI-to-ROCm integration

The real authenticated loopback API path completed one Radeon Cloud job on
2026-07-25. Browser-to-cloud validation remains open because the cloud image
did not provide `rc-tunnel` and the platform-documented fallback could not
establish a verified endpoint. See
[radeon-session-2-results.md](radeon-session-2-results.md).

BrandPilot Local keeps mock mode as the default. Real generation exists under
the explicit `/experimental/rocm` namespace and is unavailable unless
`ENABLE_EXPERIMENTAL_ROCM=true` is set before backend startup.

## Architecture

```mermaid
flowchart LR
  B["Local browser frontend"] --> T["Temporary authenticated Radeon backend tunnel<br/>Demo only"]
  T --> A["FastAPI"]
  A --> Q["Single GPU job worker"]
  Q --> S["Validated SDXL img2img pipeline"]
  S --> G["AMD Radeon through PyTorch/HIP"]
  G --> O["Project-scoped generated output"]
  O --> R["Browser review"]
```

The temporary tunnel is a demo transport, not a permanent hosted service. It
exposes only FastAPI bound to `127.0.0.1:8000`. JupyterLab, a shell, storage,
and API documentation are not exposed through it.

## API and worker

- `GET /experimental/rocm/status`
- `POST /experimental/rocm/projects/{project_id}/generate`
- `GET /experimental/rocm/jobs/{job_id}`
- `GET /experimental/rocm/jobs/{job_id}/output`

Submission returns HTTP 202 and an in-memory job identifier. Allowed states are
`queued`, `loading_model`, `preprocessing`, `generating`, `saving`,
`completed`, and `failed`. Diffusion steps are returned only from the
Diffusers step callback; there is no invented percentage or completion time.

One worker thread and one pipeline lock permit only one active GPU job. A
second active submission returns HTTP 409. Model loading is lazy and the loaded
pipeline may be reused by a later job. Generation runs outside the asynchronous
request loop. Shutdown waits for an active worker; running inference is not
described as cancellable.

## Validated model boundary

The worker accepts only:

- `stabilityai/stable-diffusion-xl-base-1.0`
- revision `462165984030d82259a11f4367a4eed129e94a7b`
- `StableDiffusionXLImg2ImgPipeline`
- `torch.float16` on `cuda`, the PyTorch API namespace used by HIP
- 768 × 768, 15 steps, strength 0.35, guidance 6.5

The fixed default seed is `20260725`; one validated integer override is
permitted per request. The pipeline requires populated `torch.version.hip`, an
available `torch.cuda` device, and an AMD/Radeon device name. It refuses CPU,
mock fallback, alternate models, IP-Adapter, ControlNet, LoRA, training, batch,
and video paths.

Output metadata records the exact model revision, GPU/device software,
input/output hashes, load/generation/total timings, and peak allocated/reserved
memory. It never returns cache paths, absolute artifact paths, internal hosts,
tunnel addresses, credentials, or account identifiers.

## Browser behavior

The operator opts in from the studio and enters the temporary backend URL and
access code at runtime. Both values are stored only in `sessionStorage`; they
are not build variables, cookies, local storage, analytics, or logs. The code
input is masked and cleared from the form after connection. Disconnect and
Clear session remove both values immediately.

The browser marks Radeon connected only after an authenticated status request
confirms AMD GPU and ROCm availability. A failed check clears stale device
information. Real mode creates one project, uploads one rights-safe asset,
submits one style and format, polls until completed or failed, retrieves the
protected output, displays measured metadata and disclosure, and persists a
human review decision.

## Limits and disable procedure

SDXL img2img may distort small packaging text or logos. “Preserve general
shape/proportions” is prompt guidance, not an identity-preservation guarantee.
Every output requires human review. Commercial production clearance is not
complete.

Disable the feature by leaving `ENABLE_EXPERIMENTAL_ROCM=false`, stopping the
temporary tunnel, and clearing the browser session. Normal mock startup does
not import or require Torch or Diffusers.
