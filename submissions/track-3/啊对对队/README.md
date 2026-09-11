# Parcel Sorter ROCm

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ROCm 7.2.1](https://img.shields.io/badge/ROCm-7.2.1-ED1C24.svg)](https://rocm.docs.amd.com/)
[![Genesis 1.2.3](https://img.shields.io/badge/Genesis-1.2.3-111111.svg)](https://github.com/Genesis-Embodied-AI/Genesis)
[![Model: Hugging Face](https://img.shields.io/badge/Model-Hugging%20Face-FFD21E.svg)](https://huggingface.co/L2658183739/agengt-vla)

**Language:** English | [Chinese documentation](README_CN.md)

Parcel Sorter ROCm runs an Agent-conditioned, v21 PI0.5 VLA-routed parcel
manipulation system in Genesis on one AMD Radeon GPU with ROCm. The Agent sets
bounded task intent, the fine-tuned VLA votes on grasp mode, and a deterministic
controller executes continuous motion under safety gates. Three delivered
hybrid episodes complete long-distance transport; strict pure-VLA control is
reported separately at 0/3.

![Five-second scripted-controller preview](docs/assets/demo_hook_5s.gif)

**Review in this order:** [result attribution](docs/RESULT_ATTRIBUTION.md),
[architecture](docs/ARCHITECTURE.md), [test report](docs/TEST_REPORT.md),
[training evidence](docs/TRAINING_EVIDENCE.md), and
[submission materials](submission_materials/README.md).

**Watch the evidence:** [three Agent+VLA hybrid episodes with overview and wrist
views](videos/v21-agent-vla-hybrid-success/README.md) · [eight-episode scripted
reference](videos/genesis_panda_8_success_reference_demo.mp4) · [Bilibili demo](https://www.bilibili.com/video/BV1Qkun6qEKn/) ·
[model and v21 adapter](https://huggingface.co/L2658183739/agengt-vla)

## 中文摘要

这是一个运行在单张 AMD Radeon GPU 与 ROCm 上的 Genesis 包裹抓取和分拣系统。仓库测试了固定单臂 Panda 工作站与轮式双臂 Bi-Franka 两种仿真形态。当前主线是 Agent 条件化 + v21 PI0.5 抓取模式路由 + 脚本连续运动：交付 3 个完整仿真回合，严格纯 VLA 闭环仍为 0/3。脚本参考控制器、混合路线和纯 VLA 评测始终分开记录。中文补充文档见 [README_CN.md](README_CN.md)。

## 1. Project Overview / 项目简介

The task starts with a parcel at a randomized pose. A robot must pick it and
place it in the requested region while Genesis supplies physics and rendering.
Two simulated embodiments are exercised in the repository:

| Simulated embodiment | Verified path | Recorded evidence |
| --- | --- | --- |
| Fixed single-arm Franka Panda | `scripts/run_demo.sh` | Scripted reference: 8/10 fixed-seed episodes |
| Omnidirectional mobile Bi-Franka with two Panda arms | `scripts/smoke_mobile_bimanual_rocm.py` and the mobile PI0.5 stack | Base motion, dual-arm smoke tests, and the separately attributed v21 hybrid route |

These are two Genesis robot configurations, not two physical robots. Their
common execution boundary is:

仓库中的“两种机器人”指两个 Genesis 仿真配置：固定单臂 Panda 与带全向底盘的
双臂 Bi-Franka，不表示两台真机，也不构成 Sim-to-Real 结果。

```text
RGB + robot state + task -> PolicyContext -> controller -> safety checks -> Genesis
```

Controllers produce `CartesianAction`; the environment executes only actions
that pass workspace, force, inverse-kinematics, and tool-command checks. The
implementation is in `src/parcel_sorter/`, with runnable entries in `scripts/`
and fixed configurations in `configs/`.

### Evidence at a glance

| Route | Recorded result | What it supports | What it does not support |
| --- | ---: | --- | --- |
| `ScriptedPickPlaceExpert + ClosedLoopSupervisor` | **8/10** fixed-seed Genesis episodes | Deterministic reference-workcell demonstration | VLA, Agent, or real-robot success |
| Raw VLA offline action envelope | **0/42** samples valid | The raw learned actions exceeded an execution boundary | Closed-loop task success |
| Safety-clipped VLA / Harness-Lite offline envelope | **42/42** samples valid | The fixed action boundary restores offline validity | 42 successful pick-and-place episodes |
| Agent-conditioned, v21 VLA-routed, scripted-motion hybrid | **3 delivered** simulation episodes | Bounded Agent conditioning and learned grasp-mode routing before scripted motion | Pure-VLA continuous action control |
| Strict pure VLA closed loop | **0/3** | The separated pure-VLA route did not complete the task | A passed learned-policy result |

![Three delivered hybrid episodes: distance and placement error](docs/assets/02_success_results.png)

The eight-trajectory demo is an untrimmed stream-copy concatenation of the
successful scripted-controller overview streams. Its source hashes, codec,
frame counts, and selection rule are recorded in
[`videos/source_manifest.json`](videos/source_manifest.json). It is Genesis
simulation, not real-robot footage.

## 2. Development and Technical Approach / 开发过程与技术方案

The project distinguishes a reference controller from learned-policy evidence
because visually plausible learned actions can still violate an executable
motion contract. The engineering response was to retain the raw-policy failure,
place bounded action validation after policy output, and report each route
separately.

The v21 route is deliberately named an **Agent-conditioned, VLA-routed,
scripted-motion hybrid**:

1. A bounded Responses Agent receives one structured task observation and may
   select only a goal, grasp family, and recovery strategy.
2. The v21 PI0.5 mode head consumes RGB-D, state, and task text, then routes a
   grasp family after a three-vote consensus.
3. A deterministic controller executes continuous pregrasp, suction, lift,
   transport, placement, and release under safety gates.

The Agent cannot emit servo actions, poses, joint targets, tool commands,
safety overrides, or checkpoint changes. The v21 VLA continuous-action path is
run in shadow mode (`applied_physics_steps=0`), so these episodes are not
pure-VLA action rollouts. See
[the v21 result record](docs/V21_AGENT_VLA_HYBRID_RESULTS.md) and
[architecture details](docs/ARCHITECTURE.md).

工程上最关键的取舍是把职责拆开：Agent 只生成高层任务条件，v21 只负责抓取
模式投票，连续运动仍由确定性控制器执行。这样可以保留学习模型的真实贡献，
同时避免把混合系统结果误写成纯 VLA 成功。

One documented SmolVLA training run completed 2,800 updates on a single Radeon
GPU. Its log records loss from 2.164 to 0.056, 6.33 updates/s mean throughput,
and 2.32 GB reported peak GPU memory. This shows that optimization ran; it does
not establish closed-loop task completion. The run, imported TensorBoard view,
and offline ablation are documented in
[training evidence](docs/TRAINING_EVIDENCE.md) and
[offline ablation results](docs/ABLATION_RESULTS.md).

## 3. Source Attribution and Dependencies / 代码来源与依赖

| Component | Upstream source | Project contribution |
| --- | --- | --- |
| Physics and rendering | [Genesis 1.2.3](https://github.com/Genesis-Embodied-AI/Genesis) | Parcel scene, sensors, controllers, Radeon scripts, recording, and tests |
| Learned-policy framework | [LeRobot 0.6.1](https://github.com/huggingface/lerobot) | Local SmolVLA/PI0.5 adapters, training, evaluation, and action contracts |
| Robot assets | Genesis-distributed Franka Panda and Apache-2.0 Bi-Franka MJCF | Fixed-arm workcell plus project-built omnidirectional mobile base integration |
| This repository | `src/parcel_sorter/`, `scripts/`, and `configs/` | Task logic, supervisor, safety gates, dataset audit, and delivery tooling |

The pinned upstream revisions are in [UPSTREAM_LOCK.json](UPSTREAM_LOCK.json).
See [third-party notices](THIRD_PARTY_NOTICES.md), the [MIT license](LICENSE),
[`requirements-lock.txt`](requirements-lock.txt), and
[`pyproject.toml`](pyproject.toml) for dependency and licensing details.

No learned weights or dataset payloads are committed to Git. The original
2,800-update SmolVLA training payload and checkpoint are no longer available;
only their manifests, hashes, audit, and log remain. A separate local
seven-episode successful-trajectory set was not used to train that checkpoint.
See [data status](data/README.md) for the exact boundary and fresh-generation
path.

固定版本、第三方许可证和本项目修改点分别记录在 `UPSTREAM_LOCK.json`、
`THIRD_PARTY_NOTICES.md` 与上表中；上游机器人资产和模型不算作原创代码。

### Model download / 模型下载

The Hugging Face repository is the model entry point. It contains the complete
PI0.5 DROID base checkpoint and the project v21 rank-16 LoRA adapter in separate
directories so the upstream base and project adaptation remain identifiable.

```bash
hf download L2658183739/agengt-vla --repo-type model \
  --local-dir models/agengt-vla

export PARCEL_PI05_BASE_MODEL="$PWD/models/agengt-vla/base/pi05-droid"
export PARCEL_PI05_V21_CHECKPOINT="$PWD/models/agengt-vla/adapters/v21"
```

The model card and manifest in the Hub repository define the exact file layout,
base revision, adapter hash, action contract, and controller attribution.

### Dataset generation / 数据生成

Dataset payloads are intentionally excluded from Git. The repository keeps the
generation and validation path needed to create a fresh LeRobot dataset:

| File | Responsibility |
| --- | --- |
| `configs/mobile_suction_collection_v1.json` | Object, physics, destination, and episode parameters |
| `scripts/collect_mobile_suction_dataset_rocm.py` | Campaign runner; preserves failures and merges verified successful shards |
| `scripts/evaluate_mobile_suction_lift_rocm.py` | One simulation rollout with overview/wrist RGB-D recording |
| `src/parcel_sorter/dataset.py` | Synchronized LeRobot state, action, task, RGB, and depth writer |
| `scripts/audit_dataset.py` | Fails closed on incomplete metadata, statistics, or camera/action contracts |

数据集大文件不上传 GitHub。上述脚本会保留失败审计记录，只把通过完整任务检查的
episode 合并为训练 shard；详细字段和命令见 [data/README.md](data/README.md)。

## 4. Team and Development Transparency / 团队与开发透明度

`2658183739` is the submitter and is responsible for the task definition,
system design, experiment execution, evidence review, documentation, and final
delivery.

GPT-5.6 Luna/Codex Runtime was used as a bounded engineering and review tool.
It is not the robot controller and is not the source of the scripted demo
trajectories. For the v21 hybrid run, the requested `gpt-5.6-luna` endpoint
returned no valid response and the audited client used its configured
`gpt-5.5` fallback; the trace records the requested and actual model without
storing credentials.

团队由提交者 `2658183739` 负责问题定义、系统设计、实验执行、证据复核和发布。
GPT-5.6 Luna/Codex Runtime 用于开发和审查，不是机器人控制器；本次成功运行实际
记录的 Agent 调用是 `gpt-5.5` fallback，仓库不保存任何 API Key。

## 5. Install and Run / 安装与运行

The recorded environment is Linux with one `gfx1100` Radeon GPU, ROCm 7.2.1,
PyTorch 2.9.1 ROCm, Genesis 1.2.3, and Python 3.12. `cuda:0` in framework
configuration denotes the HIP-compatible device interface, not NVIDIA CUDA.

推荐先运行不依赖模型和 API 的脚本参考 demo，确认 Radeon、Genesis 和录像链路；
再下载 PI0.5 基座与 v21 adapter，复现 Agent+VLA 混合路线。

### Radeon container

```bash
docker build -f Dockerfile.rocm -t parcel-sorter-rocm .
docker run --rm --device=/dev/kfd --device=/dev/dri --group-add video \
  -v "$PWD/outputs:/workspace/parcel-sorter-rocm/outputs" parcel-sorter-rocm
```

The container defaults to `scripts/run_demo.sh`, which runs one fixed-seed,
checkpoint-free scripted episode. It exits nonzero unless that episode reaches
success and writes the result to `outputs/scripted-demo/expert/`.

### Native Radeon environment

```bash
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh
bash scripts/run_demo.sh
```

The preflight requires Linux, exposed `/dev/kfd` and `/dev/dri`, and one
accessible ROCm PyTorch device. The scripted demo is the quickest reproducible
entry point; it does not load a learned checkpoint.

### Reproduce the v21 hybrid path

The v21 path needs a valid API key, a local PI0.5 base model, and the v21
adapter. Do not store any of these inputs in the repository.

```bash
export OPENAI_API_KEY="<your-key>"
export PARCEL_PI05_BASE_MODEL="/absolute/path/to/pi05-droid/model"
export PARCEL_PI05_V21_CHECKPOINT="/absolute/path/to/v21/checkpoint"

python scripts/plan_mobile_pi05_episode_with_agent.py \
  --config configs/mobile_pi05_v21_luna_agent_v1.json \
  --observation configs/mobile_pi05_agent_observation_side_box.json \
  --output outputs/v21-agent-plan.json

python scripts/build_agent_conditioned_demo_config.py \
  --source-config configs/mobile_pi05_v21_agent_hybrid_success_3_v1.json \
  --agent-plan outputs/v21-agent-plan.json \
  --output outputs/v21-agent-episodes.json \
  --shape box --max-episodes 3

python scripts/collect_mobile_suction_dataset_rocm.py \
  --config outputs/v21-agent-episodes.json \
  --output outputs/v21-agent-hybrid \
  --backend rocm --wrist-rgbd --audit-only \
  --smolvla-checkpoint "$PARCEL_PI05_V21_CHECKPOINT" \
  --policy-mode shadow --policy-hz 3 \
  --pi05-chunk-execution-protocol first-action-hold-v1 \
  --pi05-chunk-execution-steps 1 \
  --task-routing-authority agent_semantic_skill \
  --require-vla-grasp-mode \
  --record-media-all-episodes --record-wrist-video
```

The run fails closed on an invalid Agent schema or a disagreement between the
Agent-selected and VLA-routed grasp family. A completed rollout remains a
hybrid result: the VLA routes grasp mode while scripted control owns continuous
motion.

## Evidence Boundaries / 证据边界

- All reported task results are Genesis simulation results; there is no
  real-robot deployment or sim-to-real claim.
- The 42-sample offline ablation measures action-envelope validity, not task
  success or statistical significance.
- The scripted demo, hybrid results, and strict pure-VLA evaluation must never
  be combined into one success rate.
- Repository-local checks are summarized in [the test report](docs/TEST_REPORT.md).
  External publication, registration, and public-link status must be verified
  separately before submission.
