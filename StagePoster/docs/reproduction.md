# Official Reproduction Guide

## Target Environment

Verified reference:

```text
Ubuntu 24.04.4 LTS
AMD GPU with gfx1100
ROCm 7.2.1
HIP 7.2.53211
Go 1.25.0
```

## Important Assumption

These scripts **do not install the AMD kernel driver or the ROCm stack.** Start
from an image where `rocminfo` already works:

- The official AMD hackathon image
- An AMD Developer Cloud image
- Any image with a working ROCm installation

Verify before going further:

```bash
rocminfo | grep -m1 -E 'Name:.*gfx'
rocm-smi --showproductname
```

## 1. Clone

```bash
cd /workspace
git clone <STAGEPOSTER_REPOSITORY_URL> poster-engine
cd poster-engine/backend
```

> Replace the placeholder repository URL before publication.

## 2. Bootstrap

```bash
chmod +x scripts/*.sh
./scripts/bootstrap.sh
```

This installs or prepares system packages, Go 1.25.0, `uv`, the Python 3.10
ComfyUI environment, the Python 3.12 vLLM environment, ComfyUI at the verified
commit, and the backend dependencies.

## 3. Configure

```bash
cp .env.example .env
nano .env
```

At minimum verify `WORKFLOW_PATH`, `PROMPT_NODE_ID`, `SEED_NODE_ID`,
`VLM_API_KEY`, and `VLM_MODEL_PATH`.

Also confirm the four data paths point somewhere persistent. On the reference
instance they point at `/workspace/persistence/stageposter/`, **not** into the
project tree:

```bash
DB_PATH            = /workspace/persistence/stageposter/data/poster.db
STORAGE_ROOT       = /workspace/persistence/stageposter/storage/jobs
ASSET_STORAGE_ROOT = /workspace/persistence/stageposter/storage/assets
POSTER_OUTPUT_ROOT = /workspace/persistence/stageposter/storage/posters
```

## 4. Download Models

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
export HF_TOKEN=<optional-token>

./scripts/download-models.sh
```

> **`HF_HUB_DISABLE_XET=1` is not optional** where huggingface.co is
> unreachable. Setting `HF_ENDPOINT` alone is not enough: Xet-backed large files
> bypass the mirror straight to `cas-server.xethub.hf.co` and 401. Small files
> land, the directory looks populated, **and the exit code can still be 0.**
> Always verify byte sizes, not exit status.

Expected files and approximate sizes:

| Path | Bytes |
|---|---|
| `ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors` | 12309866400 |
| `ComfyUI/models/text_encoders/qwen_3_4b.safetensors` | 8044982048 |
| `ComfyUI/models/vae/ae.safetensors` | 335304388 |
| `ComfyUI/models/loras/z_image_turbo_distill_patch_lora_bf16.safetensors` | 158826336 |
| `models/Qwen3.5-9B/` | ~19 GB total |

```bash
find ComfyUI/models -type f -name '*.safetensors' -printf '%s\t%p\n' | sort -n
```

## 5. Install Workflow

Ensure this file exists:

```text
/workspace/poster-engine/workflows/z_image_poster_v1.json
```

Verify the node mapping matches `.env`:

```bash
PROMPT_NODE_ID=57:27
NEGATIVE_PROMPT_NODE_ID=57:34
SEED_NODE_ID=57:3
```

If the workflow was re-exported, node IDs may change.

> Reference-image conditioning nodes (`LoadImage` → `Canny` →
> `ModelPatchLoader` → `ZImageFunControlnet`) are **not** in this file. They are
> injected into a clone of the graph at build time, so that requests without a
> reference produce a byte-identical graph. Do not add them to the template.

## 6. Build Backend

```bash
cd /workspace/poster-engine/backend

go mod download
go test ./...
go build -o poster-backend ./cmd/server
```

## 7. Start Services

```bash
./scripts/start-all.sh
```

Startup order is vLLM → ComfyUI → backend → health checks. vLLM is started
**resident**; sleep mode is deliberately disabled because
`--enable-sleep-mode` breaks generation on ROCm 7.2 + vLLM 0.20.0.

## 8. Verify

```bash
./scripts/status.sh
./scripts/smoke-test.sh
```

`status.sh` reports one line per service (`RUNNING PID=…` / `STOPPED` /
`STALE PID FILE`) followed by HTTP checks. `smoke-test.sh` prints one
`<name> OK HTTP=<code>` line per check and ends with:

```text
STAGEPOSTER SMOKE TEST OK
```

## 9. Public Development Access

```bash
./scripts/install-cloudflared.sh
./scripts/start-dev-tunnel.sh
```

The script prints a temporary public URL and writes it to
`backend/run/public-api-url.txt`. The subdomain changes on every restart, so
never hardcode it.

> `POSTER_API_TOKEN` is empty by default, which leaves the backend
> unauthenticated. Set a real token before sharing the URL.

## 10. Full Golden E2E

The regression suite is a **Python** script — 30 routes, 127 assertions:

```bash
cd /workspace/poster-engine
.venv-vllm/bin/python scripts/e2e-test.py all
```

> Use that interpreter. The script needs Pillow to synthesize test images and
> only `.venv-vllm` has it; system `python3` fails with
> `ModuleNotFoundError: No module named 'PIL'` before the first assertion.
> Earlier revisions of this guide referenced `scripts/e2e-test.sh`, which does
> not exist.

Review it before running — it performs real GPU inference. The expected
lifecycle:

```text
create session → send requirements → generate plans → confirm plan
→ generate three candidates → select candidate → compose poster
→ review → recompose → review again → restore best round
→ finalize → retry finalize (idempotent)
```

Finalize normally ends in `completed_with_warnings` rather than `succeeded`.
That is the expected result, not a failure — see `docs/job-lifecycle.md` §9.

## 11. Capture Exact Runtime Locks

AMD image wheels may differ from generic ROCm repositories:

```bash
./scripts/export-runtime-locks.sh
```

Commit the generated lock reports after reviewing them for secrets.

## 12. Reproduction Evidence

Recommended evidence to store under `docs/evidence/`:

```text
system.txt      gpu.txt        versions.txt
go-test.txt     smoke-test.txt golden-e2e.txt
final-poster.png
review-round-1-final_poster.png
review-round-2-final_poster.png
```

## Known Environment Difference

The verified ComfyUI environment contains:

```text
torch       2.13.0+rocm7.2
torchvision 0.28.0+rocm7.2
torchaudio  2.11.0+rocm7.2
```

These exact builds may be supplied by the AMD base image. The generic installer
falls back to a compatible AMD ROCm wheel set when the exact image wheel is
unavailable. For bit-for-bit reproduction, retain both the exact AMD base image
identifier and the exported lock report.

The `site-packages` trees are large (ComfyUI ~16 GB, vLLM ~8.3 GB) and are not
backed up. `pip freeze` for both is archived by
`scripts/prepare-before-instance-kill.sh` to
`prekill/private/{comfyui,vllm}-requirements.txt` — a few KB that is the only
practical rebuild instruction for 24 GB.
