# RoboPilot — YCB Color Sorting with SmolVLA + Qwen3-VL on AMD ROCm
# RoboPilot — 基于 SmolVLA + Qwen3-VL 的 YCB 颜色分类抓取放置（AMD ROCm）

**AMD Radeon Hackathon 2026-07 · Track 3 · Physical AI Challenge**

A Franka Panda arm, simulated in the Genesis physics engine, grasps real-world YCB objects and sorts them into per-color recessed containers. The system uses a **dual-VLM hierarchical closed loop**: Qwen3-VL-8B handles high-level perception & task planning, SmolVLA-450M provides 30 Hz real-time closed-loop control.

Franka Panda 机械臂在 Genesis 物理引擎中，将 YCB 物体按颜色分类抓取放置到对应凹槽容器。系统采用**双 VLM 分层闭环**：Qwen3-VL-8B 负责视觉感知与任务规划，SmolVLA-450M 负责 30Hz 实时闭环控制。

---

## Table of Contents / 目录
1. [Environment Requirements / 环境要求](#1-environment-requirements--环境要求)
2. [Dependency Specifications / 依赖规格](#2-dependency-specifications--依赖规格)
3. [Model Weights / 模型与权重](#3-model-weights--模型与权重)
4. [Scene & Objects / 场景与物体](#4-scene--objects--场景与物体)
5. [Step-by-Step Reproduction / 分步复现流程](#5-step-by-step-reproduction--分步复现流程)
6. [Expert Demo / 专家演示](#6-expert-demo--专家演示)
7. [Evaluation Results / 评估结果](#7-evaluation-results--评估结果)
8. [Docker Deployment / Docker 部署](#8-docker-deployment--docker-部署)
9. [Project Structure / 项目结构](#9-project-structure--项目结构)
10. [Technical Report / 技术报告](#10-technical-report--技术报告)

---

## 1. Environment Requirements / 环境要求

| Component / 组件 | Version / 版本 | Requirement / 要求 |
|------------------|----------------|---------------------|
| GPU | AMD Radeon | ROCm 7.2.1, ≥48 GB VRAM (e.g. Instinct MI300X, RX 7900) |
| OS / 操作系统 | Ubuntu 24.04 | Linux (headless OK) |
| Python | 3.12 | — |
| Physics engine / 物理引擎 | Genesis 1.2.3 | GPU-parallel rigid-body solver |
| ML framework / 框架 | LeRobot 0.6.0 | SmolVLA training/eval |
| PyTorch | 2.9.1+rocm7.2.1 | ROCm backend |
| Transformers | ≥4.57 | Qwen3-VL via `AutoModelForImageTextToText` |
| Video | imageio[ffmpeg] | demo video / dataset encoding |

> 本环境为 **headless**（无显示器），Genesis 用 GPU 后端运行，无需 GUI。
> This environment is **headless** — Genesis runs on the GPU backend without a display.

---

## 2. Dependency Specifications / 依赖规格

安装依赖（Install dependencies）:

```bash
# 创建并激活虚拟环境 (Create & activate venv)
python3.12 -m venv rdna
source rdna/bin/activate

# 安装核心依赖 (Install core dependencies)
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

`requirements.txt` 完整内容（Full manifest）:

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

> **注**：`genesis-world` 需要从源码编译（含 CUDA/ROCm 内核）。首次安装耗时较长。
> **Note**: `genesis-world` is installed from source (compiles ROCm kernels), so first install is slow.

---

## 3. Model Weights / 模型与权重

| Model / 模型 | Source / 来源 | Default path / 默认路径 |
|--------------|---------------|--------------------------|
| SmolVLA-450M base | HuggingFace `lerobot/smolvla_base` | `/workspace/models/smolvla_base` |
| Qwen3-VL-8B | ModelScope `Qwen/Qwen3-VL-8B-Instruct` | `/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master` |

自动下载（Automatic download）:

```bash
# 两种权重都会下载 (Downloads both weights)
python color_sort/download_models.py
# 或指定目录 (or specify dirs)
SMOLVLA_BASE=/mnt/models/smolvla \
QWEN3VL_PATH=/mnt/models/qwen3vl \
python color_sort/download_models.py
```

> **关键注意**：`lerobot/smolvla_base` 在**离线环境不可解析**，训练/评估必须用本地路径 `--policy-path /workspace/models/smolvla_base`。Qwen3-VL 通过 ModelScope 下载（HF 常不可达）。
> **Critical**: `lerobot/smolvla_base` is unresolvable offline — always pass the local path `--policy-path /workspace/models/smolvla_base` for training/eval. Qwen3-VL is fetched via ModelScope.

---

## 4. Scene & Objects / 场景与物体

**训练物体（颜色各异，均可靠可抓）/ Training objects (distinct colors, reliably graspable):**

| Object / 物体 | Color / 颜色 | Container / 容器 | Size / 尺寸 |
|---------------|--------------|-------------------|-------------|
| 011_banana | yellow / 黄 | yellow | 6.9 cm short axis |
| 018_plum | purple / 紫 | purple | 5.3 cm |
| red_cube (geometric) | red / 红 | red | 5.0 cm cube |

**Eval 物体 / Eval object:** 014_lemon (yellow / 黄, held-out generalization)

> **物体选择准则 / Object-selection rule**: Franka 夹爪最大张开 7.62cm，可靠抓取需物体短轴 ≤6cm。圆滑大物体（apple/orange 7.2cm+）超出可靠范围，故用红色几何立方体替代。
> Franka's max gripper opening is 7.62 cm; objects with short axis ≤6 cm are reliably graspable. Large round objects (apple/orange 7.2 cm+) exceed the reliable range, so a red geometric cube is used instead.

---

## 5. Step-by-Step Reproduction / 分步复现流程

> 以下命令均在 `color_sort/` 目录下执行，并先 `source /workspace/rdna/bin/activate`。
> All commands run from `color_sort/`, after `source /workspace/rdna/bin/activate`.

### Step 1: Record the expert dataset / 录制专家数据集

```bash
cd color_sort
source /workspace/rdna/bin/activate

python record_dataset_parallel.py \
  --episodes 220 --n-envs 32 --split train \
  --repo-id color_sort/train_ycb5 --root ../datasets/train_ycb5 \
  --overwrite --jitter 0.02
```

- 每个 batch 开头重置环境；**批级 NaN 恢复**自动跳过偶发解算器发散，不中断录制
- 产出约 221 个成功 episodes（含世界+腕部相机视频 + 9D 关节动作）
- Each batch resets the environment; **batch-level NaN recovery** skips divergent batches automatically. Produces ~221 successful episodes (world+wrist camera videos + 9D joint actions).

### Step 2: Validate the dataset / 验证数据集

```bash
python inspect_dataset.py ../datasets/train_ycb5
```
Expected output (finger-action distribution, symbolic encoding): `mean≈0.014 std≈0.038 closed≈33% open≈67%`

### Step 3: Train SmolVLA / 训练 SmolVLA

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python train_policy.py smolvla \
  --repo-id color_sort/train_ycb5 \
  --steps 10000 --batch-size 64 --save-freq 5000 --num-workers 8 \
  --device cuda --policy-path /workspace/models/smolvla_base
```
- 训练耗时约 3.4 小时（batch=64, fp32），单步 ~1.2s
- 输出：`../outputs/train/smolvla_train_ycb5/checkpoints/{005000,010000}`
- Training takes ~3.4 h (batch=64, fp32, ~1.2 s/step). Outputs checkpoints at `005000` and `010000`.

### Step 4: Closed-loop evaluation / 闭环评估

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 20 --split train --seed 1000 --device cuda --jitter 0.02
```
- 结果写入 `../outputs/eval_results/train_ycb5/010000.json`
- Results are written to `../outputs/eval_results/train_ycb5/010000.json`.

### Step 5: Full closed loop with Qwen3-VL planning / 全链路闭环（Qwen3-VL 规划）

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb5/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb5 --dataset-root ../datasets/train_ycb5 \
  --episodes 3 --split train --seed 1000 --device cuda --jitter 0.02 \
  --qwen-plan     # 启用 Qwen3-VL 视觉规划（识别颜色→选目标）
```
> `--qwen-verify` 可同时启用 Qwen3-VL 放置结果验证（Stage C2）。
> `--qwen-verify` additionally enables Qwen3-VL placement verification (Stage C2).

### Step 6: Record a demo video / 录制演示视频

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
- 产出 3-5 分钟闭环演示视频（含命令行操作/执行状态/结果覆盖层）
- Produces a 3-5 min closed-loop demo video (with CLI/status/result overlays).

---

## 6. Expert Demo / 专家演示

单物体抓取放置（Single-object pick-place）:

```bash
cd color_sort
python sk_grasp_demo.py --pick red_cube     # red_cube / 011_banana / 018_plum
python sk_grasp_demo.py --pick 011_banana
python sk_grasp_demo.py --pick 018_plum
```

---

## 7. Evaluation Results / 评估结果

| Version / 版本 | Training objects / 训练物体 | Success rate / 成功率 |
|----------------|-----------------------------|------------------------|
| v6 (geometric primitives / 几何基元) | cube/cylinder | 50% |
| YCB v4 (pre-center-fix / 修复前) | banana/plum/red_cube | 70% |
| **YCB v5 (center-aligned grasp / 中心对准修复)** | **banana/plum/red_cube** | **80%** |

Per-object (YCB v5):
| Object / 物体 | Success / 成功率 |
|----------------|------------------|
| 011_banana (yellow / 黄) | **100%** |
| red_cube (red / 红) | **100%** |
| 018_plum (purple / 紫) | 43% |

Closed-loop Qwen3-VL planning + SmolVLA execution: **100%** (3/3).

> **关键修复 / Key fix**: 指尖对准物体中心（`GRASP_CENTER_DROP_FRAC 0.45→0.0`）使 red_cube 从 25%→100%，验证了"夹具未对准中心导致弹飞/滑开"的诊断。
> Aligning fingertips to the object center (`GRASP_CENTER_DROP_FRAC 0.45→0.0`) improved red_cube from 25%→100%, confirming the "misaligned grasp → eject/slip" diagnosis.

---

## 8. Docker Deployment / Docker 部署

完整可复现环境以 Docker 镜像交付（Complete reproducible environment as a Docker image）:

```bash
# On a host with Docker + exposed AMD GPU (/dev/kfd, /dev/dri)
cd docker
docker compose build
docker compose run --rm robopilot python sk_grasp_demo.py --pick red_cube
```

详见 [`docker/README.md`](docker/README.md)（构建/运行/离线模式）。

---

## 9. Project Structure / 项目结构

```
color_sort/
├── build_scene.py              # Genesis scene (YCB objects + 5-box containers)
├── scene_config.py             # layout / colors / containers / geometry objects
├── sk_grasp_demo.py            # expert pick-place (center-aligned grasp)
├── record_dataset_parallel.py  # parallel 32-env recording + NaN recovery
├── train_policy.py             # SmolVLA/ACT training wrapper
├── eval_policy.py              # closed-loop eval (Qwen3-VL plan/verify)
├── qwen_planner.py             # Qwen3-VL-8B color perception & planning
├── qwen_verifier.py            # Qwen3-VL-8B placement verification
├── record_demo_video.py        # closed-loop demo video recorder
├── download_models.py          # model weight downloader
├── inspect_dataset.py          # dataset checker
└── xml/                        # Franka model
docker/                          # Docker image build/run artifacts
docs/compose/reports/           # technical report
requirements.txt                # dependency manifest
```

---

## 10. Technical Report / 技术报告

详见 [`docs/compose/reports/technical-report.md`](docs/compose/reports/technical-report.md) —— 含架构图、AMD ROCm GPU 使用数据（利用率 99.7%、显存 16.7/51.5GB、功耗 228W/307W）、训练耗时、7 大创新点。

See [`docs/compose/reports/technical-report.md`](docs/compose/reports/technical-report.md) — architecture diagram, AMD ROCm GPU telemetry (99.7% util, 16.7/51.5 GB VRAM, 228W/307W power), training time, and 7 innovations.
