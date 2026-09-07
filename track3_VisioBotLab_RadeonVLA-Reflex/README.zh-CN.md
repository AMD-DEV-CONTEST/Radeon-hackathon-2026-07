# RadeonVLA-Reflex

> **语言：** 中文项目指南。英文版见 [README.md](README.md)。
> 发布材料与 Pull Request 正文按仓库规则使用英文。

RadeonVLA-Reflex 是运行在单张 AMD Radeon GPU 上的**可中断、可恢复 VLA 执行层**。
Track 3 基准使用 Genesis、Franka Panda、LeRobot 和 SmolVLA，把 5 种水果分到 4 个
可由语言指定的盘位。水果分拣是验证场景，核心贡献是让 action-chunk 策略在操作员改指令
或抓取失败时仍能及时、安全、可量化地响应。

主要设计内容：

1. **分级任务套件（L1–L4）** — 命名目标、空间指代、有序多物体序列、属性/规则分拣；
2. **语言可区分的双碗** — 左/右容器需由自然语言消歧；
3. **可中断指令执行** — 中途更改语言指令会使过期动作块失效；
4. **失败感知恢复** — 空抓/超时检测、确定性撤回重试，以及显式启用的严格物理精确恢复；
5. **安全监视器** — 进入仿真前的关节限幅与速率限制；
6. **单卡 ROCm 路径** — 在 AMD Radeon 上完成仿真、数据、训练、推理与评测；
7. **多目标部分完成指标** — 按层级成功率与部分完成率统计长时序任务。
8. **可重复压力测试** — 确定性移动目标水果/盘位，并支持 baseline 与 Reflex 消融；
9. **结构化证据** — 自动输出 JSON、CSV、摘要、真实 checkpoint 哈希和带实时状态的视频；
10. **中断安全采集** — 未完成数据只保留在 staging，不会覆盖上一份有效数据。

> 发布状态（2026-08-05）：严格物理的 20×100 Physical-2K 数据集和累计约 200K 步
> SmolVLA 推理权重均已完成。固定 20 任务 × 5 seed 正式基准中，学习策略首次成功
> **36/100**，显式启用严格物理 Precision-Reflex 后最终成功 **91/100**（Wilson 95%
> 区间 **83.8–95.2%**）。全部 100 条 episode（包括 9 条失败）均保留在不可变结果文件中。
> 公开展示视频以原始 **20K** 权重作为定性模型样例；50K 与 200K 权重保留为独立下载项。

| 公开产物 | 不可变 revision |
|---|---|
| [SmolVLA-1K 权重](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k) — 主要 20K 展示权重 | `abcca9f2b313e378b554449016b520b8117016fe` |
| [Physical-1K 数据集](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_1k) — 1,000 episodes / 232,658 frames | `b0f72c60e9100739fd82bd498c8f3d9bed7b75af` |
| [Physical-2K 数据集](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k) — 2,000 episodes / 468,889 frames | `2779b7c5566df9072bb9a7c43335d6203ea97887` |
| [SmolVLA 累计 50K 权重](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k_50k) | `59f6f0ad720054505667a652fe07e03d65e82915` |
| [SmolVLA 累计 200K 权重](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k) | `1ea32da3d59ce0905d0f1331bc3c6643e42beb7e` |
| [评测视频与证据](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos) | `6de24191322c76c53405d6686b9ae74989073414` |

- 公开项目网站：**https://zzw-rgb.github.io/Radeon-hackathon-2026-07/**
- 交互式证据控制台：**https://zzw-rgb.github.io/Radeon-hackathon-2026-07/console.html**
- B 站正式成片：**https://www.bilibili.com/video/BV1B4M26SEZg/**
- Track 3 正式提交：**https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/110**

本目录为完整、自包含的项目单元。从仓库根目录进入
`track3_VisioBotLab_RadeonVLA-Reflex/`，可按本文档复现系统。

## 项目信息

| 字段 | 内容 |
|---|---|
| 赛道 | Track 3 — Physical AI Challenge |
| 团队 | VisioBot Lab |
| 项目 | RadeonVLA-Reflex |
| 队长 | 周振威 |
| 队员 | 留安格、王浩然 |
| 单位 | 南京理工大学 |

## 目标应用

目标应用为食品处理、实验室自动化与小批量物流中的语言可重配置分拣单元。
操作员可以在机器人运动途中修改目标；运行层立即作废旧动作块、进入安全张爪保持，
并能对检测到的空抓执行有界恢复；精确恢复模式继续禁止水果瞬移和抓取粘附。

### 任务层级

| 层级 | 名称 | 策略需要完成的内容 | 示例 |
|---|---|---|---|
| **L1** | 基础命名 | 水果 × 碗（5 种水果 × 4 个碗） | `banana_white_left`、`apple_blue_left`、`orange_blue_right` |
| **L2** | 空间指代 | 随机化后解析 *最左/最右/最近/最远* | `leftmost_to_white_left`、`leftmost_to_blue_left` |
| **L3** | 多步序列 | 同一局内完成**有序**多物体放置 | `seq_banana_white_left_lemon_white_right`、`seq_apple_blue_left_orange_blue_right` |
| **L4** | 属性规则 | 将颜色/形状规则展开为多个子目标 | `rule_yellow_white_left_purple_white_right`、`rule_red_blue_left_orange_blue_right` |

场景物体：**香蕉、柠檬、李子、苹果、橙子**，以及 **四个正放固定碗** —
**左侧白+蓝，右侧白+蓝**（均可放置水果）。

套件（CLI `--suite`）：

| 套件 | 内容 |
|---|---|
| `basic` | 仅 L1（20 个任务） |
| `spatial` | L2 |
| `multistep` | L3 |
| `rules` | L4 |
| `advanced` | L2+L3+L4 |
| `full` | 全部层级（显式启用的高级基准） |

Physical-2K 每项任务保存两条确定性的采集原文。主控制器基准使用相同原文但采用
不相交 seed；`--instruction-source heldout` 单独用于改写泛化测试。空间与规则任务
在位姿随机化后由 `radeonvla.grounding` 在 episode 开始时解析。

## 系统架构

![RadeonVLA-Reflex 英文架构框架：语言指令、World RGB、Wrist RGB 与本体状态输入 SmolVLA；动作经 SafetyMonitor、CommandSession 和 FailureDetector 加 RecoveryPolicy 后进入 Genesis](docs/figures/architecture-framework-en.svg)

闭环流程：

1. **感知与状态** — World RGB、Wrist RGB，以及机器人与夹爪状态（关节角 \(q\)、关节速度 \(\dot q\)、夹爪开度 \(g\)、末端位姿 \(T\)）。
2. **SmolVLA 策略** — 视觉-语言-动作模型输出动作块（\(\Delta q\)、\(\Delta g\)、\(\Delta T\) 等）。
3. **执行安全监视器（Reflex）** — 关节限幅/速率限制、指令版本变更、空抓检测与确定性撤回；显式 `--precision-recovery` 模式在学习策略失败后调用严格物理几何恢复，并单独记录其贡献。
4. **Genesis Franka 双碗仿真** — 只执行安全指令；下一帧观测回馈闭环。

学习栈为语言与视觉条件下的端到端关节位置控制。
指令作废与恢复为策略外的**确定性安全层**（不重新训练 VLA）。评测可确定性注入水果或盘位
移动，并把 `RUNNING / INTERRUPTED / RECOVERING / PRECISION RECOVERY / SUCCESS` 直接叠加到演示视频。

技术报告与项目网站统一使用这张英文矢量框架图，浏览器和 PDF 放大后仍保持清晰。

## 仓库结构

```text
track3_VisioBotLab_RadeonVLA-Reflex/
├── README.md                 # 英文项目指南
├── README.zh-CN.md           # 中文说明
├── pyproject.toml
├── environment.local.yml
├── requirements.local.txt
├── requirements.remote.txt
├── configs/
│   ├── base.yaml
│   ├── train.yaml
│   └── eval.yaml
├── src/radeonvla/
│   ├── scene.py              # Genesis 双碗场景
│   ├── expert.py             # 脚本分拣专家
│   ├── record_dataset.py     # LeRobot 数据采集（训练前置）
│   ├── validate_dataset.py   # 训练前数据集检查
│   ├── train_policy.py       # SmolVLA / ACT 训练封装
│   ├── evaluate.py           # 闭环评测 + 中断 + 恢复
│   ├── download_artifacts.py # 固定 revision 的公开产物下载器
│   ├── safety.py             # 指令会话、安全与失败处理
│   ├── pipeline.py           # 阶段编排 / all-smoke
│   ├── benchmark.py          # 吞吐 / 延迟
│   ├── setup_assets.py       # 填充机器人/YCB 资产
│   ├── check_env.py
│   └── submission_audit.py
├── scripts/
│   ├── run_pipeline_smoke.sh
│   └── run_full_remote.sh
├── tests/
├── docs/
├── artifacts/
├── reports/
├── docker/Dockerfile
└── assets/README.md
```

数据集、权重、生成视频、实验输出、凭证与私有配置不纳入 Git。

## 依赖策略

PyTorch 需按执行平台单独安装，不与项目其余依赖混装：

- 已验证的本地开发环境使用 CPU 版 PyTorch（导入与单测）；
- 远程 Radeon 环境须使用与 ROCm 版本匹配的 PyTorch HIP 构建；
- `pyproject.toml` 中故意不写通用 PyPI `torch` 依赖；
- 安装其余依赖时不得覆盖已验证的 PyTorch 构建。

核心版本：

| 组件 | 版本 |
|---|---|
| Python | 3.12 |
| PyTorch（本地） | 2.9.1+cpu |
| torchvision（本地） | 0.24.1+cpu |
| torchaudio（本地） | 2.9.1+cpu |
| Genesis | 1.1.2 |
| LeRobot | 0.6.0 |

Track 3 starter 文档中给出了 ROCm 7.2.1 专用 wheel 集合。仅当远程实例报告
ROCm 7.2.1 且 Python 3.12 时使用该集合；否则在安装 `requirements.remote.txt`
前先选择匹配的官方 ROCm 轮子。

## 仿真资产（复现必需）

网格资产已**纳入本仓库**的 `assets/`（约 42 MB）。普通 `git clone` 即可运行，
无需额外私有文件源。

| 路径 | 内容 |
|---|---|
| `assets/ycb/011_banana`、`013_apple`、`014_lemon`、`017_orange`、`018_plum`、`024_bowl` | YCB 网格 |
| `assets/robots/franka/` | Franka Emika Panda MJCF |
| `assets/SHA256SUMS` | 完整性校验 |

```bash
python -m radeonvla.setup_assets           # 已存在则跳过
python -m radeonvla.setup_assets --verify  # 校验 SHA256
python -m radeonvla.setup_assets --download # 缺失时的可选网络回退
```

来源与说明：[`assets/README.md`](assets/README.md)、[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

- YCB Object and Model Set：https://www.ycbbenchmarks.com/object-models/
- YCB 数据门户：http://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/
- Genesis（Franka 也可从已安装的 genesis 包恢复）：https://github.com/Genesis-Embodied-AI/Genesis

## 本地开发环境

已验证的本地开发机为 Ubuntu 22.04.5（联想拯救者 R7000 2021，Ryzen 5 5600H，
16 GB 内存，NVIDIA RTX 3050）。该机器为开发客户端，**不是**最终 AMD 执行机。

### 重建 Conda 环境

```bash
conda env create -f environment.local.yml
conda activate radeonvla-dev

python -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  torch==2.9.1+cpu \
  torchvision==0.24.1+cpu \
  torchaudio==2.9.1+cpu

python -m pip install -r requirements.local.txt
python -m pip install -e .
python -m pip check
```

### 校验本地环境

```bash
conda activate radeonvla-dev
python -m radeonvla.check_env --json docs/environment.local.json
python -m radeonvla.setup_assets
pytest
ruff check src tests
python -m radeonvla.submission_audit
```

本地运行用于验证可移植性与代码质量，不计入 Radeon 性能指标。

## 远程 AMD Radeon 环境

使用带持久 PVC 的 Radeon Cloud 实例，并只暴露一张 GPU。
ROCm 轮子细节见 `docs/REMOTE_ROCM_SETUP.md`。

### 1. 审计未改动的实例

```bash
uname -a
cat /etc/os-release
python3 --version
rocminfo | head -n 100
amd-smi
python3 - <<'PY'
import torch
print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY
```

### 2. 克隆到持久卷

```bash
cd /workspace
mkdir -p visiobot
cd visiobot
git clone https://github.com/zzw-rgb/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
git checkout submission/track3-visiobotlab-radeonvla-reflex
cd track3_VisioBotLab_RadeonVLA-Reflex
```

### 3. 创建或复用 Python 3.12 环境

若镜像已在 Python 3.12 中提供验证过的 PyTorch HIP 构建：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
```

### 4. 安装其余依赖

```bash
python -m pip install -r requirements.remote.txt
python -m pip install -e .
python -m pip check
python - <<'PY'
import torch
assert torch.version.hip is not None
assert torch.cuda.is_available()
print(torch.__version__, torch.version.hip, torch.cuda.get_device_name(0))
PY
```

### 5. 严格 AMD 校验

```bash
export HIP_VISIBLE_DEVICES=0
bash scripts/check_remote_amd.sh
```

## 下载公开数据集、权重与评测证据

所有发布仓库均为公开仓库，并固定到本文开头列出的不可变 revision；下载不需要
Hugging Face 登录或任何私有文件。下载器会生成 `downloads/public_artifacts.json`
回执，并由 `huggingface_hub` 校验下载对象。

```bash
# 只列出全部仓库、revision 与本地目录，不进行网络下载。
python -m radeonvla.download_artifacts --list

# 推荐展示复现组合：Physical-1K + 公开 20K 权重 + 评测证据。
python -m radeonvla.download_artifacts \
  --artifact physical-1k model-20k evaluation-videos

# 正式基准输入：Physical-2K + 累计 200K 权重。
python -m radeonvla.download_artifacts \
  --artifact physical-2k model-200k

# 可选：下载两个数据集、三个权重版本和完整评测证据。
python -m radeonvla.download_artifacts --all
```

等价 Make 目标为 `make download-demo` 和 `make download-all`。固定本地路径如下：

| 名称 | 本地目录 | 用途 |
|---|---|---|
| `physical-1k` | `datasets/radeonvla_reflex_physical_1k` | 复现主要 20K 展示 |
| `physical-2k` | `datasets/radeonvla_reflex_physical_2k` | 最终数据校验、续训与正式评测 |
| `model-20k` | `checkpoints/radeonvla_reflex_smolvla_1k_20k` | 主要定性策略权重 |
| `model-50k` | `checkpoints/radeonvla_reflex_smolvla_1k_50k` | 中间对比权重 |
| `model-200k` | `checkpoints/radeonvla_reflex_smolvla_2k_200k` | 正式 Precision-Reflex 评测权重 |
| `evaluation-videos` | `downloads/radeonvla_reflex_evaluation_videos` | 视频、JSON/CSV 证据与校验和 |

长时间运行前，先校验数据集并实际加载权重：

```bash
python -m radeonvla.validate_dataset \
  --repo-id a3124371940/radeonvla_reflex_physical_1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --expected-episodes 1000 --episodes-per-task 50 --require-strict-physics

python - <<'PY'
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

path = "checkpoints/radeonvla_reflex_smolvla_1k_20k"
policy = SmolVLAPolicy.from_pretrained(path)
print("loaded:", path, "parameters:", sum(p.numel() for p in policy.parameters()))
PY
```

权重加载检查与平台无关；闭环仿真、ROCm 性能和正式评测必须在上文校验通过的
AMD 环境中运行。

## 端到端流水线（已实现）

以下阶段均以 `python -m radeonvla.<module>` 入口提供。

| 阶段 | 模块 | 作用 |
|---|---|---|
| 资产 | `setup_assets` | 将 Franka + YCB 网格放入 `assets/` |
| 环境检查 | `check_env` | Torch / HIP / Genesis 报告 |
| 场景 | `scene` | 双碗 Genesis 冒烟与可选截图 |
| 专家 | `expert` | 语言条件下的脚本抓取放置 |
| **采集** | **`record_dataset`** | **采集 LeRobot 演示（训练前置）** |
| 校验 | `validate_dataset` | 训练前 schema / NaN / 图像检查 |
| 训练 | `train_policy` | 经 `lerobot-train` 训练 SmolVLA / ACT |
| 评测 | `evaluate` | 闭环策略 + 中断 + 恢复 |
| 基准 | `benchmark` | 仿真吞吐 / 可选推理延迟 |
| 编排 | `pipeline` | 阶段编排（`all-smoke` 等） |

### 一键脚本（推荐）

| 脚本 / Make 目标 | 作用 |
|---|---|
| `bash scripts/run_all_local.sh` / `make all-local` | 本地一键：资产→场景→专家→**采集**→校验 |
| `bash scripts/run_record.sh` / `make record-local` | 仅采集（可用 `EPISODES`、`SUITE`、`BACKEND`） |
| `bash scripts/run_expert_demo.sh` / `make expert-demo` | 脚本专家演示（基础/困难混合） |
| `bash scripts/run_pipeline_smoke.sh` / `make smoke` | 1 episode 冒烟 + 训练 dry-run |
| `bash scripts/run_full_remote.sh` / `make remote-full` | AMD 全流程：检查→采集→训练→评测→基准 |
| `bash scripts/check_local.sh` / `make check` | 环境 + 审计 + pytest + ruff |
| `bash scripts/check_remote_amd.sh` / `make remote-check` | 严格 ROCm 门禁 |

```bash
# 本地：采集 10 条 basic episode
EPISODES=10 SUITE=basic bash scripts/run_record.sh

# 本地：一键流水线
EPISODES=5 bash scripts/run_all_local.sh

# 快速冒烟
make smoke

# AMD Radeon
EPISODES=200 SUITE=basic bash scripts/run_full_remote.sh
```

变量说明见 [`scripts/README.md`](scripts/README.md)。可选从 `.env.example` 复制 `.env`。

### 模块形式的本地冒烟

```bash
bash scripts/run_pipeline_smoke.sh
# 等价：
python -m radeonvla.pipeline all-smoke --backend cpu --episodes 1 --task banana_white_left
```

执行顺序：资产 → 环境 → 场景 → 专家(1) → **采集(1)** → 校验 → 训练 dry-run。

### 分步命令

```bash
# 环境与资产
python -m radeonvla.check_env
python -m radeonvla.check_env --require-amd --init-genesis
python -m radeonvla.setup_assets
python -m radeonvla.submission_audit

# M1 — 场景冒烟
python -m radeonvla.scene --backend cpu --steps 100 --save-frames
python -m radeonvla.scene --backend amdgpu --steps 100 --save-frames

# M2 — 脚本专家（基础 + 多步）
python -m radeonvla.expert --task banana_white_left --episodes 5 --backend cpu
python -m radeonvla.expert --task seq_triple_sort --episodes 3 --backend cpu
python -m radeonvla.expert --suite advanced --episodes 8 --backend amdgpu

# M3 — 主基准数据采集（20 个 L1 任务，每项至少 10 个成功示范）
python -m radeonvla.record_dataset \
  --episodes 200 \
  --suite basic \
  --repo-id visiobot/radeonvla_reflex \
  --dataset-root datasets/radeonvla_reflex \
  --backend amdgpu \
  --require-coverage

# 仅在新数据完成验证后安全替换旧数据
python -m radeonvla.record_dataset --episodes 200 --suite basic --require-coverage \
  --overwrite --discard-incomplete \
  --repo-id visiobot/radeonvla_basic --dataset-root datasets/radeonvla_basic

# 采集时可选域随机
python -m radeonvla.record_dataset --episodes 400 --suite basic --require-coverage \
  --dr-appearance --dr-object-color --dr-runtime --backend amdgpu

# 正式纯物理数据：20 个任务，每个恰好 50 条成功 episode。
# 默认关闭运动学粘附、物体瞬移和 placement nudge，并为每条数据写原子证书。
SOURCE_COMMIT="$(git rev-parse HEAD)" python -m radeonvla.record_dataset \
  --episodes-per-task 50 --suite basic --require-coverage \
  --repo-id YOUR_HF_NAMESPACE/radeonvla-reflex-physical-1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --dr-appearance --dr-object-color --dr-runtime --dr-rebuild-every 20 \
  --max-attempts 10000 --backend amdgpu

# 中断后续采；参数和源码 revision 必须与原子进度记录一致。
SOURCE_COMMIT="$(git rev-parse HEAD)" python -m radeonvla.record_dataset \
  --episodes-per-task 50 --suite basic --require-coverage \
  --repo-id YOUR_HF_NAMESPACE/radeonvla-reflex-physical-1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --dr-appearance --dr-object-color --dr-runtime --dr-rebuild-every 20 \
  --max-attempts 10000 --backend amdgpu --resume-incomplete

# 训练前校验数据集
python -m radeonvla.validate_dataset \
  --repo-id visiobot/radeonvla_reflex \
  --dataset-root datasets/radeonvla_reflex

# 正式发布门禁
python -m radeonvla.validate_dataset \
  --repo-id YOUR_HF_NAMESPACE/radeonvla-reflex-physical-1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --expected-episodes 1000 --episodes-per-task 50 --require-strict-physics

# 实测卡片元数据就绪后使用交互式登录。write token 不写入命令、
# 仓库文件或 shell 历史。
hf auth login

# 先私有发布。命令会再次验证 20×50，上传完整数据和自包含 checkpoint，
# 再从不可变 Hub revision 回下载并验证。
python -m radeonvla.publish_hf \
  --dataset-repo YOUR_HF_NAMESPACE/radeonvla-reflex-physical-1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --dataset-validation artifacts/dataset_validation_physical_1k.json \
  --model-repo YOUR_HF_NAMESPACE/radeonvla-reflex-smolvla-1k \
  --policy-path outputs/train/smolvla_physical_1k/checkpoints/020000/pretrained_model \
  --private

# 只有私有版本回载验证通过后才显式转为公开。
python -m radeonvla.publish_hf \
  --dataset-repo YOUR_HF_NAMESPACE/radeonvla-reflex-physical-1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --dataset-validation artifacts/dataset_validation_physical_1k.json \
  --model-repo YOUR_HF_NAMESPACE/radeonvla-reflex-smolvla-1k \
  --policy-path outputs/train/smolvla_physical_1k/checkpoints/020000/pretrained_model \
  --public --confirm-public-release

# M4/M5 — 训练 SmolVLA（需要非空数据集）
python -m radeonvla.train_policy smolvla \
  --repo-id visiobot/radeonvla_reflex \
  --dataset-root datasets/radeonvla_reflex \
  --steps 10000 --device cuda

# 正式 100 条 Precision-Reflex 基础评测（20 tasks × 5 seeds）
python -m radeonvla.evaluate \
  --policy-path outputs/train/smolvla_radeonvla_reflex_physical_2k_continue_100k_to200k/checkpoints/100000/pretrained_model \
  --repo-id a3124371940/radeonvla_reflex_physical_2k \
  --dataset-root datasets/radeonvla_reflex_physical_2k \
  --suite basic --episodes 100 --seed-start 52000 \
  --instruction-source collected --max-retries 0 --precision-recovery \
  --backend amdgpu --output artifacts/evaluation.precision_reflex_basic100.json

# 可中断性演示（在第 0 局中途注入指令变更）
python -m radeonvla.evaluate \
  --policy-path outputs/train/smolvla_radeonvla_reflex/checkpoints/last/pretrained_model \
  --repo-id visiobot/radeonvla_reflex \
  --dataset-root datasets/radeonvla_reflex \
  --interrupt-demo --save-video --backend amdgpu

# 吞吐 / 延迟
python -m radeonvla.benchmark --backend amdgpu --steps 500
```

### 远程全流程脚本（AMD）

```bash
export HIP_VISIBLE_DEVICES=0
bash scripts/run_full_remote.sh
# 或自定义：
EPISODES=200 SUITE=basic TRAIN_STEPS=10000 bash scripts/run_full_remote.sh
```

自包含 Docker（Track 3 推荐）：

```bash
docker build --pull -f docker/Dockerfile -t radeonvla-reflex:rocm7.2.1 .
docker run --rm -it --device=/dev/kfd --device=/dev/dri \
  --group-add video --group-add render \
  --ipc=host --shm-size=8g --security-opt seccomp=unconfined \
  -v "$PWD/datasets":/workspace/radeonvla-reflex/datasets \
  -v "$PWD/checkpoints":/workspace/radeonvla-reflex/checkpoints \
  -v "$PWD/outputs":/workspace/radeonvla-reflex/outputs \
  -v "$PWD/artifacts":/workspace/radeonvla-reflex/artifacts \
  radeonvla-reflex:rocm7.2.1 check-amd

docker compose -f docker/compose.yaml run --rm radeonvla check-amd
```

源码、配置、脚本、资产和测试已经包含在镜像内，仅挂载可变的数据、权重和结果。
入口命令包括 `help`、`check-amd`、`smoke`、`remote-full`、`reflex-demo` 和 `shell`。

## 数据规格

每帧包含：

```text
observation.images.world   # HWC uint8 RGB
observation.images.wrist   # HWC uint8 RGB
observation.state          # 9 维 qpos（7 臂 + 2 指）
action                     # 9 维绝对关节位置目标
task                       # 自然语言指令
```

| 项 | 值 |
|---|---|
| 动作类型 | 绝对关节位置 |
| 维度 | 9 |
| 关节顺序 | panda_joint1..7, panda_finger_joint1..2 |
| 夹爪范围 | [0.0, 0.04] m |
| 控制 / 数据集帧率 | 20 Hz（仿真 100 Hz，降采样） |
| 图像尺寸 | 320×240 |

种子划分：

| 划分 | 种子 |
|---|---|
| 严格冒烟 | 12000–12999 |
| 训练来源 | 21000–26999、71000–76039 |
| 验证 | 40000–40999 |
| 正式 100 条评测 | 52000–52099 |
| 中断 / 恢复 | 60000–60999 |

## 评测协议

正式主协议为 20 个 L1 任务各 5 个独立 seed episode，共 100 个，并使用数据集
实际采集原文。held-out 改写泛化另行测试；中断和目标移动压力测试使用代表性任务
与独立 seed；L2–L4 只有在实际训练评测后才报告。

报告指标：

- 任务成功率；
- 物体正确率；
- 目标正确率；
- 首次尝试成功；
- 允许恢复后的最终成功；
- 恢复成功；
- 安全中断率与指令到动作作废的步数；
- 按任务和扰动场景统计的成功率；
- 完成时间均值与 P95；
- 推理延迟 P50 与 P95；
- 仿真步每秒；
- 训练样本每秒；
- 训练与推理峰值显存。

包括失败在内的每个 episode 均保留在 JSON 中。正式证据自动写入
`artifacts/evaluation.json`、`evaluation.csv` 和 `summary.md`，模式为
`artifacts/evaluation.schema.json`。视频会显示当前指令、Reflex 状态、版本、重试和延迟。

## 复现已发布系统

按以下层级执行，可在昂贵评测前先排除基本代码问题：

1. **CPU 代码门禁：**安装本地环境，运行 `make check` 和 `make smoke`；
2. **公开产物门禁：**运行 `make download-demo`，校验 Physical-1K，并执行上文的权重加载命令；
3. **AMD 单任务回放：**用公开 20K 权重运行一个固定 seed episode；
4. **AMD 正式复现：**下载 Physical-2K 和 200K 权重，以发布参数运行 20 任务 × 5 seed。

```bash
# 在 AMD Radeon 上复现一项已发布的 20K 策略任务。
python -m radeonvla.evaluate \
  --policy-path checkpoints/radeonvla_reflex_smolvla_1k_20k \
  --repo-id a3124371940/radeonvla_reflex_physical_1k \
  --dataset-root datasets/radeonvla_reflex_physical_1k \
  --backend amdgpu --tasks banana_white_left --episodes 1 \
  --seed-start 53001 --instruction-source collected --max-retries 0 \
  --save-video --output outputs/reproduction/20k_banana_white_left.json

# 可选：使用公开数据集和权重进行短程续训。
python -m radeonvla.train_policy smolvla \
  --policy-path checkpoints/radeonvla_reflex_smolvla_1k_20k \
  --repo-id a3124371940/radeonvla_reflex_physical_2k \
  --dataset-root datasets/radeonvla_reflex_physical_2k \
  --steps 1000 --batch-size 4 --device cuda \
  --output-dir outputs/reproduction/train_20k_on_physical_2k

# 在 AMD Radeon 上复现正式 100 次评测。
python -m radeonvla.evaluate \
  --policy-path checkpoints/radeonvla_reflex_smolvla_2k_200k \
  --repo-id a3124371940/radeonvla_reflex_physical_2k \
  --dataset-root datasets/radeonvla_reflex_physical_2k \
  --backend amdgpu --suite basic --episodes-per-task 5 \
  --seed-start 52000 --instruction-source collected --max-retries 0 \
  --precision-recovery --save-video \
  --output outputs/reproduction/formal100.json
```

将输出 JSON 与 `artifacts/evaluation.json` 对照；schema 位于
`artifacts/evaluation.schema.json`。最终发布不依赖私有账号、未公开文件或源码修改。

## 交付物

| 交付物 | 状态 | 链接 |
|---|---|---|
| 源代码 | 公开发布分支 | [GitHub 源码](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/tree/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex) |
| 可复现 README | 本文件 / 英文版 | README.md |
| 技术报告（MD） | 持续维护的源文档 | reports/RadeonVLA-Reflex-Technical-Report.md |
| 技术报告 PDF | A4、5 页、最终审计输入 | [技术报告 PDF](reports/RadeonVLA-Reflex-Technical-Report.pdf) |
| 公开项目网站 | GitHub Pages 部署已核验 | [RadeonVLA-Reflex 网站](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/) |
| B 站正式成片 | 已发布的项目解说与完整演示 | [在 B 站观看 RadeonVLA-Reflex](https://www.bilibili.com/video/BV1B4M26SEZg/) |
| Track 3 正式提交 | 比赛 Pull Request | [AMD-DEV-CONTEST PR #110](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/110) |
| 3 分钟以上解说成片 | 200.0 秒、1080p30 H.264/AAC、自然英文旁白与内嵌中英双语字幕 | [播放公开视频](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/videos/radeonvla-reflex-3min.mp4) |
| 20K 模型成功回放 | 香蕉与柠檬均首次执行成功；命令/实测夹爪已张开；释放后继续仿真 2.0 秒 | [Hugging Face 证据](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos) |
| 20 任务采集成功库 | 每个“水果 × 目标碗”任务各一条认证成功轨迹，附 episode、seed、证书和校验和来源 | [Hugging Face 证据](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos/tree/6de24191322c76c53405d6686b9ae74989073414/videos/task_success_world) |
| 主要模型权重 | 公开 20K 权重，revision `abcca9f2…016fe` | [Hugging Face 20K 模型](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k) |
| 其他模型权重 | 公开 50K 与 200K revision | [50K](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k_50k) · [200K](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k) |
| 数据集 | Physical-1K 与 Physical-2K | [1K](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_1k) · [2K](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k) |
| 评测视频库 | 成功回放、三分钟成片、机器可读证据与校验和 | [Hugging Face 证据](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos) |
| 交互式证据控制台 | 只读基准浏览器，20 个任务均匹配一条 Physical-2K 成功样例 | [进入控制台](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/console.html) |
| 原始评测结果 | 100/100 episode 全部保留 | `artifacts/evaluation.json`、`.csv`、`summary.md` |
| SHA256 校验和 | 最终发布包 | `artifacts/SHA256SUMS` |
| Docker 镜像定义 | 自包含运行定义 | docker/Dockerfile |

发布文档：

- `docs/DATASET_CARD.md`
- `docs/MODEL_CARD.md`
- `reports/RadeonVLA-Reflex-Technical-Report.md`

```bash
python -m radeonvla.submission_audit
python -m radeonvla.submission_audit --final
```

## 参考与致谢

- AMD Track 3 比赛仓库
- AMD Radeon Cloud 用户指南
- Track 3 Franka fruit-pick demo（Genesis + LeRobot on ROCm 流程参考）
- Genesis World
- Hugging Face LeRobot / SmolVLA
- YCB Object and Model Set

上游参考仓库在本项目目录外维护。本树为 RadeonVLA-Reflex 项目代码；
依赖声明见 `THIRD_PARTY_NOTICES.md`。

## 团队

**VisioBot Lab** · 南京理工大学

| 成员 | 角色 | 工作量 | 主要工作 |
|---|---|---:|---|
| **周振威** | 队长 / 主程 | 约 70% | 总体架构；Genesis、专家策略、Reflex 与流水线实现；采集总控；SmolVLA 训练评测；AMD 部署；网站和发布工程 |
| 留安格 | 语言与前端质检 | 约 15% | 任务语言模式校对、采集指令一致性检查、网站国际化质检和中英文技术文档 |
| 王浩然 | 数据与复现质检 | 约 15% | 数据证书抽检、评测指标汇总、复现命令核验和产物校验和打包 |

## 提交

官方 Pull Request 标题：

```text
Track 3, VisioBot Lab, RadeonVLA-Reflex
```

所有提交材料、项目说明与 Pull Request 正文使用英文。
评审快速入口与英文提交摘要见 [`docs/SUBMISSION.md`](docs/SUBMISSION.md)。
