# Docker Deployment — RoboPilot YCB Color Sorting (AMD ROCm)

This directory contains everything needed to build and run the full
RoboPilot pipeline in a container on an AMD Radeon GPU.

> **Note**: The current sandbox cannot *execute* Docker (nested containers are
> blocked: `unshare: operation not permitted`). These files are the complete,
> ready-to-build deliverable — build them on any host with Docker + an exposed
> AMD GPU.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage-less image: ROCm base + Genesis + LeRobot + project |
| `docker-compose.yml` | GPU-passthrough (`/dev/kfd`, `/dev/dri`) run config |
| `entrypoint.sh` | Container entrypoint — downloads model weights, then execs command |
| `.dockerignore` | Keeps the build context lean (no weights/datasets/outputs) |

## Requirements (host)

- Docker ≥ 24 (with `docker compose` plugin)
- An AMD GPU exposed on the host at `/dev/kfd` and `/dev/dri`
  (ROCm 7.2.1-compatible, e.g. Instinct MI300 / Radeon RX 7900)
- ~20 GB free disk for the image + ~18 GB for model weights

## Build

```bash
# from repo root (docker/ is used via docker compose)
cd docker
docker compose build
```

Or directly:

```bash
docker build -f docker/Dockerfile -t robopilot-ycb:latest .
```

## Run

### Interactive shell
```bash
docker compose run --rm robopilot bash
```

### Expert single-object pick-place
```bash
docker compose run --rm robopilot python sk_grasp_demo.py --pick red_cube
docker compose run --rm robopilot python sk_grasp_demo.py --pick 011_banana
```

### Closed-loop evaluation (SmolVLA policy)
```bash
docker compose run --rm robopilot python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 20 --split train --seed 1000 --device cuda --jitter 0.02
```

### Full closed loop with Qwen3-VL planning
```bash
docker compose run --rm robopilot python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 3 --split train --seed 1000 --device cuda --jitter 0.02 --qwen-plan
```

## Model weights

The entrypoint auto-downloads missing weights on first run:
- **SmolVLA base** (`lerobot/smolvla_base`) → HuggingFace Hub
- **Qwen3-VL-8B** (`Qwen/Qwen3-VL-8B-Instruct`) → ModelScope
  (use `USE_HF=1` to pull Qwen3-VL from HuggingFace if reachable)

To avoid re-downloading, mount a host directory:
```bash
mkdir -p ../models
docker compose run --rm -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 robopilot ...
```
Or pre-populate `../models/` using `color_sort/download_models.py` on the host:
```bash
SMOLVLA_BASE=$PWD/models/smolvla_base \
QWEN3VL_PATH=$PWD/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master \
python color_sort/download_models.py
```

## Offline mode

If the Docker host has no internet, mount pre-downloaded weights and force
offline mode (see above). Genesis is installed at build time, so only model
weights need the network at runtime.
