# Radeon Cloud session 1 results

## Result

**Successful controlled validation.** A real SDXL image-to-image generation ran
locally on one AMD Radeon Cloud GPU through PyTorch/HIP. The generated image,
measured metadata, and sanitized execution evidence are in
`evidence/radeon-session-1/`.

This validates the standalone inference path only. The FastAPI/web application
still uses its disclosed mock pipeline.

## Cloud session

| Item | Verified value |
|---|---|
| Date | 2026-07-25 |
| Launch click | 03:39:05.583 UTC |
| Ready | 03:39:44.456 UTC |
| Destroy click / confirmation | 04:00:57.458 / 04:01:05.309 UTC |
| No active instance verified | 04:02:58.289 UTC |
| Ready-to-removal duration | 23 minutes 13.833 seconds |
| Starting / final credits | 5 / 5 |
| Profile-displayed consumption | 0 credits |
| Time-proportional estimate | about 0.39 credit at the listed 1 credit/GPU-hour; not an observed charge |
| Template | `BrandPilot-Track1` |
| Container | AMD OneClick Base, ROCm 7.2.1, Python 3.12 |
| Deploy / visibility | Notebook/JupyterLab; profile only |
| Storage | Persistent (PVC), verified at runtime |
| Persistent capacity | 98 GiB total, about 93 GiB free before model download |
| Active instances afterward | None |

## Hardware and software

| Item | Measured value |
|---|---|
| GPU | AMD Radeon Graphics (`gfx1100`) |
| GPU count | 1 |
| Total GPU memory | 51,522,830,336 bytes (48 GiB) |
| Compute units | 96 |
| PyTorch | `2.9.1+gitff65f5b` |
| HIP/ROCm reported by PyTorch | `7.2.53211-e1a6bc5663` |
| Python | 3.12.3 |
| Diffusers | 0.39.0 |
| Transformers | 4.57.6 |
| Accelerate | 1.13.0 |
| Safetensors | 0.7.0 |

`rocm-smi` measured 98% GPU use and 30% allocated VRAM during generation.

## Model and generation

| Item | Measured value |
|---|---|
| Model | `stabilityai/stable-diffusion-xl-base-1.0` |
| Selection reason | Detected memory was above the 16 GiB SDXL threshold |
| Exact revision | `462165984030d82259a11f4367a4eed129e94a7b` |
| Download status | Complete; only SDXL was downloaded |
| Observed fetch phase | about 110 seconds |
| Persistent cache size | 14 GiB |
| Pipeline | `StableDiffusionXLImg2ImgPipeline` |
| Input / output | 768 × 768 / 768 × 768 |
| Steps | 15 |
| Strength | 0.35 |
| Guidance scale | 6.5 |
| Seed | 20260725 |
| Cold model load | 132.295 seconds, including fetch and pipeline loading |
| Generation | 222.111 seconds |
| Total smoke-test duration | 357.706 seconds |
| Peak allocated GPU memory | 14,396,438,528 bytes (13.41 GiB) |
| Peak reserved GPU memory | 15,365,832,704 bytes (14.31 GiB) |
| CPU offload | No |
| Attention slicing | No |
| Output SHA-256 | `bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452` |
| Result | Success |

The rights-safe input was `examples/browser-test-product.png`. The generated
artifact is `evidence/radeon-session-1/generated-output.png`.

## Verified, local-only, and still planned

Verified on Radeon Cloud:

- persistent PVC storage
- `rocm-smi` and `rocminfo`
- PyTorch HIP device detection
- direct fp16 SDXL loading without CPU offload
- one genuine image-to-image output with measured timings and memory
- instance destruction and zero-active confirmation

Tested locally only:

- CPU/no-ROCm refusal behavior
- selection and OOM retry unit tests
- the mock web workflow

Still planned:

- connecting the proven image call to FastAPI
- IP-Adapter and mask/compositing validation for product preservation
- warm-run latency and repeatability
- production license and commercial-use clearance
- quality acceptance criteria for packaging text and logos

## Errors and workarounds

- The terminal defaulted to `/usr/bin/python`, which had no PyTorch. The AMD
  image's preinstalled ROCm environment was correctly located at
  `/opt/venv/bin/python`; PyTorch was not installed or replaced.
- GitHub cloning failed because the container could not validate TLS with its
  installed CA bundle. TLS verification was not disabled. The exact
  `249af765c219434f1749bc0b8a9812c392f26faf` git archive was hashed locally,
  uploaded privately, re-hashed on the PVC, and extracted.
- The uploaded shell wrapper had CRLF line endings. A session-only LF conversion
  was applied and `bash -n` passed. The repository now enforces LF for `*.sh`.
- AMD's preinstalled AITER emitted a non-fatal JIT warning. Diffusers continued
  with the available backend and generation succeeded.

## Evidence and next step

The committed evidence is deliberately small and sanitized. Model weights,
the Hugging Face cache, raw environment values, instance/account identifiers,
authenticated URLs, and internal host/registry details are excluded.

Recommended next phase: connect this exact, lazy-loaded SDXL configuration to a
FastAPI-only experimental endpoint while keeping the main application in mock
mode, then validate IP-Adapter plus masking before claiming product preservation.
