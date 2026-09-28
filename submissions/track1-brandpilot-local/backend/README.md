# BrandPilot backend

FastAPI service for project configuration, validated uploads, explicit mock
generation, human review, and a disabled-by-default experimental ROCm job API.

Run from this directory with `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. Storage defaults to `storage/`; uploads are limited to 10 MB and must be valid PNG, JPEG, or WebP images. Default CORS permits the local frontend at both `http://localhost:3000` and `http://127.0.0.1:3000`; authenticated experimental mode still requires an explicit non-wildcard origin list.

Normal startup does not require Torch, Diffusers, ROCm, or a GPU. The
experimental namespace is enabled only with `ENABLE_EXPERIMENTAL_ROCM=true`.
It accepts one active job, lazy-loads the exact validated SDXL revision on an
AMD HIP device, and never falls back to CPU or mock. See
`docs/fastapi-rocm-integration.md` and `.env.radeon.example`.

The real loopback API path completed one Radeon Cloud job in session 2.
Session 2b verified the official authenticated browser transport. A failed
model-load retry exposed and fixed a worker bug: the reusable pipeline is now
cached only after `load_model()` succeeds. Full browser generation was not
completed during the bounded session. Session 2c verified the repaired
fresh-pod runtime and authenticated loopback startup, but the official tunnel's
assigned hostname did not resolve publicly, so no new public API or browser
generation claim is made.
