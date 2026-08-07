# ComfyUI + SDXL-Turbo installer (Radeon Cloud)

`scripts/setup_comfyui_radeon.sh` installs a pinned ComfyUI checkout and the
SDXL-Turbo checkpoint into a Radeon Cloud persistent directory, for the
generation backend used by SpriteFusion 2D's `generate.*` RPCs
(`sprite_workshop/generate/comfyui.py`).

Preview every command before touching disk or network:

```bash
scripts/setup_comfyui_radeon.sh --dry-run
```

Run for real once you have accepted the model license yourself (see below)
and exported an access token:

```bash
export SPRITE_WORKSHOP_HF_TOKEN=hf_xxx   # your own token, not committed anywhere
scripts/setup_comfyui_radeon.sh
```

## Disk requirement

Budget roughly **10-15 GB free** under the persistent root:

| Item | Approx. size |
|---|---|
| ComfyUI git checkout | ~0.3-0.5 GB |
| Independent venv (excluding torch, which is reused, not duplicated) | ~1-2 GB |
| SDXL-Turbo fp16 checkpoint (`sd_xl_turbo_1.0_fp16.safetensors`) | ~6.9 GB |

The script never installs its own torch/torchvision/torchaudio; it reuses
the image's mirrored ROCm PyTorch via `PYTHONPATH`, so there is no second
multi-GB torch install.

## Source and pinning

- ComfyUI: cloned from `SPRITE_WORKSHOP_COMFY_REPO`
  (default `https://github.com/comfyanonymous/ComfyUI.git`, the official
  upstream repo) and checked out at `SPRITE_WORKSHOP_COMFY_REF` (default
  `0.30.0`, the version pinned in `docs/luna-workpack/PUBLIC_KNOWLEDGE.md`
  section 3). `PUBLIC_KNOWLEDGE.md` records that version string, not a raw
  git commit SHA; if the upstream tag differs, override
  `SPRITE_WORKSHOP_COMFY_REF` explicitly rather than trusting a silent
  default.
- Checkpoint: `sd_xl_turbo_1.0_fp16.safetensors`, downloaded from
  `SPRITE_WORKSHOP_MODEL_URL` (default: the official
  `stabilityai/sdxl-turbo` Hugging Face repo). Its SHA-256
  (`e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26`) is
  the value pinned in `PUBLIC_KNOWLEDGE.md` and is verified after every
  download. An existing file with a matching hash is skipped (idempotent
  re-run); an existing file with a mismatched hash makes the script fail
  loudly instead of silently overwriting it.

## License

SDXL-Turbo is distributed under Stability AI's model license on its
Hugging Face model card. This script:

- prints the model card / license URL before any download and never
  proceeds automatically,
- never accepts the license on your behalf,
- requires you to supply your own `SPRITE_WORKSHOP_HF_TOKEN` (or `HF_TOKEN`)
  from an account that has already accepted the license,
- uses that token only in-memory for a single download request header; it
  is never written to a file, `.netrc`, log, or receipt.

See also `THIRD_PARTY_NOTICES.md` (tracked separately under task D03) for
the full list of third-party components and licenses.

## Environment variables

All root paths and pins are overridable; see `scripts/setup_comfyui_radeon.sh --help`
for the full, authoritative list. Names follow the existing
`SPRITE_WORKSHOP_*` convention from `scripts/start_comfyui.sh` so a later
start/stop/health script (R03) can reuse the same defaults:

`SPRITE_WORKSHOP_COMFY_ROOT`, `SPRITE_WORKSHOP_COMFY_VENV`,
`SPRITE_WORKSHOP_ROCM_SITE`, `SPRITE_WORKSHOP_BASE_PYTHON`,
`SPRITE_WORKSHOP_COMFY_REPO`, `SPRITE_WORKSHOP_COMFY_REF`,
`SPRITE_WORKSHOP_MODEL_DIR`, `SPRITE_WORKSHOP_MODEL_FILENAME`,
`SPRITE_WORKSHOP_MODEL_URL`, `SPRITE_WORKSHOP_MODEL_SHA256`,
`SPRITE_WORKSHOP_MODEL_LICENSE_URL`, `SPRITE_WORKSHOP_HF_TOKEN` (or
`HF_TOKEN`).

## What this script does not do

- No `apt`/`apt-get` install or upgrade of any kind.
- No CUDA torch install; the new venv is isolated but reuses the mirrored
  ROCm torch via `PYTHONPATH` (same mechanism as `scripts/start_comfyui.sh`).
- No real ~6.9 GB download unless run without `--dry-run` and with a valid
  token from an account that already accepted the license.
