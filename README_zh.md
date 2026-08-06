# RoboPilot — 基于 SmolVLA + Qwen3-VL 的 YCB 颜色分类抓取放置（AMD ROCm）

**AMD Radeon Hackathon 2026-07 · Track 3 · Physical AI Challenge**

Franka Panda 机械臂在 Genesis 物理引擎中，将 YCB 物体按颜色分类抓取放置到对应的凹槽容器中。系统采用**双 VLM 分层闭环**：Qwen3-VL-8B 负责视觉感知与任务规划，SmolVLA-450M 负责 30Hz 实时闭环控制。

> **英文版见 [README.md](README.md)** · For English, see [README.md](README.md).

---

## 目录
1. [环境要求](#1-环境要求)
2. [依赖规格](#2-依赖规格)
3. [模型与权重](#3-模型与权重)
4. [场景与物体](#4-场景与物体)
5. [分步复现流程](#5-分步复现流程)
6. [专家演示](#6-专家演示)
7. [评估结果](#7-评估结果)
8. [Docker 部署](#8-docker-部署)
9. [项目结构](#9-项目结构)
10. [技术报告](#10-技术报告)

---

## 1. 环境要求

| 组件 | 版本 | 要求 |
|------|------|------|
| GPU | AMD Radeon | ROCm 7.2.1，≥48GB VRAM（如 Instinct MI300X、RX 7900） |
| 操作系统 | Ubuntu 24.04 | Linux（支持无头 headless 运行） |
| Python | 3.12 | — |
| 物理引擎 | Genesis 1.2.3 | GPU 并行刚体求解器 |
| 框架 | LeRobot 0.6.0 | SmolVLA 训练/评估 |
| PyTorch | 2.9.1+rocm7.2.1 | ROCm 后端 |
| Transformers | ≥4.57 | Qwen3-VL（`AutoModelForImageTextToText`） |
| 视频 | imageio[ffmpeg] | 演示视频 / 数据集编码 |

> 本环境为 **无头（headless）** 模式，Genesis 用 GPU 后端运行，无需显示器。

---

## 2. 依赖规格

安装依赖：

```bash
# 创建并激活虚拟环境
python3.12 -m venv rdna
source rdna/bin/activate

# 安装核心依赖
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

`requirements.txt` 完整内容：

```text
# Genesis 物理模拟
genesis-world @ git+https://github.com/Genesis-Embodied-AI/Genesis.git@817debb7411a230d20837c747dc9c19619b19757

# VLM（Qwen3-VL-8B）
transformers>=4.57
accelerate
modelscope
huggingface_hub
datasets

# 策略学习（SmolVLA / LeRobot 0.6.0）
lerobot==0.6.0

# 视觉
opencv-python-headless
imageio[ffmpeg]

# 核心
numpy
pillow
pyyaml
requests
safetensors
```

> **注意**：`genesis-world` 从源码安装（需编译 ROCm 内核），首次安装耗时较长。

---

## 3. 模型与权重

| 模型 | 来源 | 默认路径 |
|------|------|---------|
| SmolVLA-450M 基础 | HuggingFace `lerobot/smolvla_base` | `/workspace/models/smolvla_base` |
| Qwen3-VL-8B | ModelScope `Qwen/Qwen3-VL-8B-Instruct` | `/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master` |

自动下载：

```bash
# 下载两种权重
python color_sort/download_models.py
# 或指定自定义目录
SMOLVLA_BASE=/mnt/models/smolvla \
QWEN3VL_PATH=/mnt/models/qwen3vl \
python color_sort/download_models.py
```

> **关键注意**：`lerobot/smolvla_base` 在**离线环境不可解析**，训练/评估必须用本地路径 `--policy-path /workspace/models/smolvla_base`。Qwen3-VL 通过 ModelScope 下载（HF 常不可达）。

---

## 4. 场景与物体

**训练物体（颜色各异，均可靠可抓）：**

| 物体 | 颜色 | 容器 | 尺寸 |
|------|------|------|------|
| 011_banana | 黄 | yellow | 6.9cm 短轴 |
| 018_plum | 紫 | purple | 5.3cm |
| red_cube（几何） | 红 | red | 5.0cm 立方体 |

**Eval 物体：** 014_lemon（黄，held-out 泛化）

> **物体选择准则**：Franka 夹爪最大张开 7.62cm，可靠抓取需物体短轴 ≤6cm。圆滑大物体（apple/orange 7.2cm+）超出可靠范围，故用红色几何立方体替代。

---

## 5. 分步复现流程

> 以下命令均在 `color_sort/` 目录下执行，并先 `source /workspace/rdna/bin/activate`。

### 步骤 1：录制专家数据集

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

### 步骤 2：验证数据集

```bash
python inspect_dataset.py ../datasets/train_ycb5
```
预期输出（手指动作分布，符号编码）：`mean≈0.014 std≈0.038 closed≈33% open≈67%`

### 步骤 3：训练 SmolVLA

```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python train_policy.py smolvla \
  --repo-id color_sort/train_ycb5 \
  --steps 10000 --batch-size 64 --save-freq 5000 --num-workers 8 \
  --device cuda --policy-path /workspace/models/smolvla_base
```
- 训练耗时约 3.4 小时（batch=64, fp32，单步 ~1.2s）
- 输出：`../outputs/train/smolvla_train_ycb5/checkpoints/{005000,010000}`

### 步骤 4：闭环评估

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

### 步骤 5：全链路闭环（Qwen3-VL 规划）

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

### 步骤 6：录制演示视频

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

---

## 6. 专家演示

单物体抓取放置：

```bash
cd color_sort
python sk_grasp_demo.py --pick red_cube     # red_cube / 011_banana / 018_plum
python sk_grasp_demo.py --pick 011_banana
python sk_grasp_demo.py --pick 018_plum
```

---

## 7. 评估结果

| 版本 | 训练物体 | 成功率 |
|------|---------|--------|
| v6（几何基元） | cube/cylinder | 50% |
| YCB v4（修复前） | banana/plum/red_cube | 70% |
| **YCB v5（中心对准修复）** | **banana/plum/red_cube** | **80%** |

分物体（YCB v5）：
| 物体 | 成功率 |
|------|--------|
| 011_banana（黄） | **100%** |
| red_cube（红） | **100%** |
| 018_plum（紫） | 43% |

闭环 Qwen3-VL 规划 + SmolVLA 执行：**100%**（3/3）。

> **关键修复**：指尖对准物体中心（`GRASP_CENTER_DROP_FRAC 0.45→0.0`）使 red_cube 从 25%→100%，验证了"夹具未对准中心导致弹飞/滑开"的诊断。

---

## 8. Docker 部署

完整可复现环境以 Docker 镜像交付：

```bash
# 在装有 Docker + AMD GPU（/dev/kfd、/dev/dri）的主机上
cd docker
docker compose build
docker compose run --rm robopilot python sk_grasp_demo.py --pick red_cube
```

详见 [`docker/README.md`](docker/README.md)（构建/运行/离线模式）。

---

## 9. 项目结构

```
color_sort/
├── build_scene.py              # Genesis 场景构建（YCB 物体 + 5-box 容器）
├── scene_config.py             # 布局/颜色/容器/几何物体配置
├── sk_grasp_demo.py            # 专家抓取放置（中心对准）
├── record_dataset_parallel.py  # 并行 32 环境录制 + NaN 恢复
├── train_policy.py             # SmolVLA/ACT 训练封装
├── eval_policy.py              # 闭环评估（Qwen3-VL 规划/验证）
├── qwen_planner.py             # Qwen3-VL-8B 颜色感知与规划
├── qwen_verifier.py            # Qwen3-VL-8B 放置验证
├── record_demo_video.py        # 闭环演示视频录制
├── download_models.py          # 模型权重下载
├── inspect_dataset.py          # 数据集检查
└── xml/                        # Franka 模型
docker/                          # Docker 镜像构建/运行产物
docs/compose/reports/           # 技术报告
requirements.txt                # 依赖清单
```

---

## 10. 技术报告

详见 [`docs/compose/reports/technical-report.md`](docs/compose/reports/technical-report.md) —— 含架构图、AMD ROCm GPU 使用数据（利用率 99.7%、显存 16.7/51.5GB、功耗 228W/307W）、训练耗时、7 大创新点。
