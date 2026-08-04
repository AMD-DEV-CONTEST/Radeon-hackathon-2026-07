# Final claim audit

This register is the single wording boundary for the README, application,
profile, presentation, demo, evidence index, and official submission package.

## Verified

| Claim | Approved wording | Evidence |
|---|---|---|
| Product description | BrandPilot Local is an AMD Radeon-powered creative studio prototype that converts product images and campaign briefs into reviewable, platform-ready marketing concepts. | `frontend/`, `backend/`, local tests, final screenshots |
| GPU | One AMD Radeon Graphics device (`gfx1100`) with 48 GiB reported memory was detected on Radeon Cloud. | `docs/radeon-session-1-results.md`, `evidence/radeon-session-1/pytorch-gpu-summary.json` |
| ROCm/HIP | PyTorch reported HIP/ROCm `7.2.53211-e1a6bc5663`. | `docs/radeon-session-1-results.md` |
| PyTorch | The verified run used PyTorch `2.9.1+gitff65f5b`, exposing the Radeon device through `torch.cuda`. | `evidence/radeon-session-1/pytorch-gpu-summary.json` |
| Real generation | Real SDXL image-to-image inference completed on AMD Radeon with ROCm. | `evidence/radeon-session-1/generated-output.png`, metadata, hash |
| Model | `stabilityai/stable-diffusion-xl-base-1.0`, exact revision `462165984030d82259a11f4367a4eed129e94a7b`. | `evidence/radeon-session-1/generation-metadata.json` |
| Parameters | 768 x 768, 15 steps, strength 0.35, guidance 6.5, seed 20260725. | `evidence/radeon-session-1/generation-metadata.json` |
| Performance | Cold load 132.295 s; generation 222.111 s; total smoke test 357.706 s; peak allocated 13.41 GiB; peak reserved 14.31 GiB. | `docs/radeon-session-1-results.md` |
| Output integrity | Output SHA-256 `bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452`. | `evidence/radeon-session-1/generation-metadata.json` |
| API integration | One authenticated FastAPI-to-Radeon loopback job completed and an Approved review state persisted. | `docs/radeon-session-2-results.md`, `evidence/radeon-session-2/session-summary.json` |
| Official tunnel | Official `rc-tunnel 0.3.0` installed and activated against a loopback FastAPI service. | `docs/radeon-session-2c-results.md`, `docs/radeon-session-3-results.md` |
| Browser transport subset | In Session 2b, Chrome reached the authenticated backend through the official tunnel with valid TLS/CORS, then created a project and uploaded an image. | `docs/radeon-session-2b-results.md` |
| Final blocker | The official browser-edge completion remained blocked because the platform-assigned rc-tunnel hostname did not resolve in public DNS. | `docs/radeon-session-3-results.md`, sanitized DNS evidence |
| Safe shutdown | Every paid instance was destroyed; final evidence shows no active instance. | Session result docs and screenshots |

## Implemented but not fully validated

- Experimental frontend connection, polling, authenticated protected-image
  fetch, blob cleanup, disconnect cleanup, review, and refresh-recovery logic.
- Single-job worker, lazy model loading, pipeline reuse, no CPU fallback, and
  no mock fallback in experimental mode.
- Product/project JSON persistence and human-review APIs.

These behaviors are covered by local automated tests. They are not described
as a fully completed public browser-to-Radeon workflow.

## Demonstrated in mock mode

- Product image upload and campaign brief configuration.
- Four style directions and multiple output formats.
- Review, edit, mock regenerate, and refresh persistence in the local browser.
- Desktop and mobile responsive experience.

Mock concepts are always labelled `Mock` or `Mock campaign concept`; no GPU use
is implied.

## Blocked by official platform issue

- Final protected output retrieval and rendering through the official public
  tunnel.
- Browser-side real-generation progress through all 15 steps.
- Browser-side persistence of a real Radeon result/review after refresh.

The final retry stopped at the DNS gate before model load or generation. No
unofficial tunnel, TLS bypass, host override, or second retry was used.

## Planned / not completed

- IP-Adapter, ControlNet, LoRA, masking/compositing, fine-tuning, and video.
- Product identity, logo, and packaging-text preservation validation.
- Warm-run repeatability or comparative optimization benchmarks.
- Permanent public hosting, production security review, and commercial model
  clearance.

## Prohibited claims

Do not claim full browser-to-Radeon end to end success, production readiness,
permanent hosting, Vercel deployment, product/logo/text preservation,
IP-Adapter validation, model training, fine-tuning, commercial clearance, or
benchmarks that were not run.
