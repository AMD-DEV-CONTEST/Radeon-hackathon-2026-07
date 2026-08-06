# ChromaSort-VLA — YCB Color Sorting with SmolVLA + Qwen3-VL on AMD ROCm

**AMD Radeon Hackathon 2026-07 · Track 3 · Physical AI Challenge**

A Franka Panda arm, simulated in the Genesis physics engine, grasps real-world YCB objects and sorts them into per-color recessed containers. The system uses a **dual-VLM hierarchical closed loop**: Qwen3-VL-8B handles high-level perception & task planning, while SmolVLA-450M provides 30 Hz real-time closed-loop control.

![Interface Display](docs/image/Interface%20Display.png)

> **中文版见 [README_zh.md](README_zh.md)** · For Chinese, see [README_zh.md](README_zh.md).

---

## Table of Contents
1. [Environment Requirements](#1-environment-requirements)
2. [Dependency Specifications](#2-dependency-specifications)
3. [Model Weights](#3-model-weights)
4. [Scene & Objects](#4-scene--objects)
5. [Step-by-Step Reproduction](#5-step-by-step-reproduction)
6. [Expert Demo](#6-expert-demo)
7. [Evaluation Results](#7-evaluation-results)
8. [Docker Deployment](#8-docker-deployment)
9. [Project Structure](#9-project-structure)
10. [Technical Report](#10-technical-report)

---

## 1. Environment Requirements

| Component | Version | Requirement |
|-----------|---------|-------------|
| GPU | AMD Radeon | ROCm 7.2.1, ≥48 GB VRAM (e.g. Instinct MI300X, RX 7900) |
| OS | Ubuntu 24.04 | Linux (headless OK) |
| Python | 3.12 | — |
| Physics engine | Genesis 1.2.3 | GPU-parallel rigid-body solver |
| ML framework | LeRobot 0.6.0 | SmolVLA training/eval |
| PyTorch | 2.9.1+rocm7.2.1 | ROCm backend |
| Transformers | ≥4.57 | Qwen3-VL via `AutoModelForImageTextToText` |
| Video | imageio[ffmpeg] | demo video / dataset encoding |

> This environment is **headless** — Genesis runs on the GPU backend without a display.

---

## 2. Dependency Specifications

Install dependencies:

```bash
# Create & activate a virtual environment
python3.12 -m venv rdna
source rdna/bin/activate

# Install core dependencies
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

Full `requirements.txt` manifest:

```text
# Genesis physics simulation
genesis-world @ git+https://github.com/Genesis-Embodied-AI/Genesis.git@817debb7411a230d20837c747dc9c19619b19757

# VLM (Qwen3-VL-8B)
transformers>=4.57
accelerate
modelscope
huggingface_hub
datasets

# Policy learning (SmolVLA / LeRobot 0.6.0)
lerobot==0.6.0

# Vision
opencv-python-headless
imageio[ffmpeg]

# Core
numpy
pillow
pyyaml
requests
safetensors
```

> **Note**: `genesis-world` is installed from source (compiles ROCm kernels), so the first install is slow.

---

## 3. Model Weights

| Model | Source | Default path |
|-------|--------|--------------|
| SmolVLA-450M base | HuggingFace `lerobot/smolvla_base` | `/workspace/models/smolvla_base` |
| Qwen3-VL-8B | ModelScope `Qwen/Qwen3-VL-8B-Instruct` | `/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master` |

Automatic download:

```bash
# Downloads both weights
python color_sort/download_models.py
# Or specify custom dirs
SMOLVLA_BASE=/mnt/models/smolvla \
QWEN3VL_PATH=/mnt/models/qwen3vl \
python color_sort/download_models.py
```

> **Critical**: `lerobot/smolvla_base` is unresolvable offline — always pass the local path `--policy-path /workspace/models/smolvla_base` for training/eval. Qwen3-VL is fetched via ModelScope.

---

## 4. Scene & Objects

**Training objects (distinct colors, reliably graspable):**

| Object | Color | Container | Size |
|--------|-------|-----------|------|
| 011_banana | yellow | yellow | 6.9 cm short axis |
| 018_plum | purple | purple | 5.3 cm |
| red_cube (geometric) | red | red | 5.0 cm cube |

**Eval object:** 014_lemon (yellow, held-out generalization)

> **Object-selection rule**: Franka's max gripper opening is 7.62 cm; objects with short axis ≤6 cm are reliably graspable. Large round objects (apple/orange 7.2 cm+) exceed the reliable range, so a red geometric cube is used instead.

---

## 5. Step-by-Step Reproduction

> All commands run from `color_sort/`, after `source /workspace/rdna/bin/activate`.

### Step 1: Record the expert dataset

```bash
cd color_sort
source /workspace/rdna/bin/activate

python record_dataset_parallel.py \
  --episodes 220 --n-envs 32 --split train \
  --repo-id color_sort/train_ycb5 --root ../datasets/train_ycb5 \
  --overwrite --jitter 0.02
```

- Each batch resets the environment; **batch-level NaN recovery** skips divergent batches automatically.
- Produces ~221 successful episodes (world + wrist camera videos + 9D joint actions).

### Step 2: Validate the dataset

```bash
python inspect_dataset.py ../datasets/train_ycb5
```
Expected output (finger-action distribution, symbolic encoding): `mean≈0.014 std≈0.038 closed≈33% open≈67%`.

### Step 3: Train SmolVLA

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python train_policy.py smolvla \
  --repo-id color_sort/train_ycb5 \
  --steps 10000 --batch-size 64 --save-freq 5000 --num-workers 8 \
  --device cuda --policy-path /workspace/models/smolvla_base
```
- Training takes ~3.4 h (batch=64, fp32, ~1.2 s/step).
- Outputs checkpoints: `../outputs/train/smolvla_train_ycb5/checkpoints/{005000,010000}`.

### Step 4: Closed-loop evaluation

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 20 --split train --seed 1000 --device cuda --jitter 0.02
```
- Results are written to `../outputs/eval_results/train_ycb5/010000.json`.

### Step 5: Full closed loop with Qwen3-VL planning

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 3 --split train --seed 1000 --device cuda --jitter 0.02 \
  --qwen-plan     # enable Qwen3-VL scene planning (perceive color → pick target)
```
> `--qwen-verify` additionally enables Qwen3-VL placement verification (Stage C2).

### Step 6: Record a demo video

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python record_demo_video.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 12 --seed 1000 --jitter 0.02 --qwen-plan --rotate \
  --out ../outputs/demo_closed_loop.mp4
```
- Produces a 3-5 min closed-loop demo video (with CLI/status/result overlays).
- **Demo video link**: `outputs/demo_closed_loop.mp4` (4.59 min, 960×544, 20 fps)

---

## 6. Expert Demo

Single-object pick-place:

```bash
cd color_sort
python sk_grasp_demo.py --pick red_cube     # red_cube / 011_banana / 018_plum
python sk_grasp_demo.py --pick 011_banana
python sk_grasp_demo.py --pick 018_plum
```

---

## 7. Evaluation Results

| Version | Training objects | Success rate |
|---------|------------------|--------------|
| v6 (geometric primitives) | cube/cylinder | 50% |
| YCB v4 (pre-center-fix) | banana/plum/red_cube | 70% |
| **YCB v5 (center-aligned grasp)** | **banana/plum/red_cube** | **80%** |

Per-object (YCB v5):
| Object | Success |
|--------|---------|
| 011_banana (yellow) | **100%** |
| red_cube (red) | **100%** |
| 018_plum (purple) | 43% |

Closed-loop Qwen3-VL planning + SmolVLA execution: **100%** (3/3).

> **Key fix**: Aligning fingertips to the object center (`GRASP_CENTER_DROP_FRAC 0.45→0.0`) improved red_cube from 25%→100%, confirming the "misaligned grasp → eject/slip" diagnosis.

---

## 8. Docker Deployment

Complete reproducible environment as a Docker image:

```bash
# On a host with Docker + exposed AMD GPU (/dev/kfd, /dev/dri)
cd docker
docker compose build
docker compose run --rm robopilot python sk_grasp_demo.py --pick red_cube
```

See [`docker/README.md`](docker/README.md) for build/run/offline instructions.

---

## 9. Project Structure

```
color_sort/
├── build_scene.py              # Genesis scene (YCB objects + 5-box containers)
├── scene_config.py             # layout / colors / containers / geometry objects
├── sk_grasp_demo.py            # expert pick-place (center-aligned grasp)
├── randomize.py                # per-episode environment randomization (slot jitter)
├── record_dataset_parallel.py  # parallel 32-env recording + NaN recovery
├── train_policy.py             # SmolVLA/ACT training wrapper
├── eval_policy.py              # closed-loop eval (Qwen3-VL plan/verify)
├── qwen_planner.py             # Qwen3-VL-8B color perception & planning
├── qwen_verifier.py            # Qwen3-VL-8B placement verification
├── record_demo_video.py        # closed-loop demo video recorder
├── download_models.py          # model weight downloader
├── inspect_dataset.py          # dataset checker
└── paths.py                    # shared output/dataset paths
docker/                          # Docker image build/run artifacts
docs/compose/reports/           # technical report
requirements.txt                # dependency manifest
```

---

## 10. Technical Report

See [`docs/compose/reports/technical-report.md`](docs/compose/reports/technical-report.md) — architecture diagram, AMD ROCm GPU telemetry (99.7% util, 16.7/51.5 GB VRAM, 228W/307W power), training time, and 7 innovations.
