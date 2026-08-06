# 可复现性说明

[English](REPRODUCIBILITY.md) | 中文

本文档面向比赛评审人员，说明如何设置环境、获取依赖和外部制品、运行系统，并复现技术报告中的主要结果。

> 结果冻结日期：2026-08-05。所有命令从仓库根目录执行。新输出写入`reproductions/`，不得覆盖提交结果。

## 1. 复现层级

| 层级 | 内容 | 需要数据/权重 | 需要新训练 |
|---|---|---:|---:|
| A | 阅读报告、图表和精简结果 | 否 | 否 |
| B | Python语法、CLI和汇总脚本 | 否 | 否 |
| C | 模型加载、单回合闭环 | 是 | 否 |
| D | 完整推理测速与严格正确性 | 是 | 否 |
| E | 300回合闭环A/B | 是 | 否 |
| F | 从数据生成到重新训练 | 否（自行生成） | 是 |

建议评委先完成A–D。E和F耗时较长，不是阅读提交材料的前置条件。

## 2. 已验证环境

| 项目 | 版本 |
|---|---|
| OS | Ubuntu 24.04 |
| Python | 3.12.3 |
| ROCm | 7.2.1；结果JSON中HIP为`7.2.53211-e1a6bc5663` |
| PyTorch | `2.9.1+rocm7.2.1.gitff65f5bc` |
| torchvision | `0.24.0+rocm7.2.1.gitb919bd0c` |
| torchaudio | `2.9.0+rocm7.2.1.gite3c6ee2b` |
| Triton | `3.5.1+rocm7.2.1.gita272dfa8` |
| LeRobot | 0.6.0 |
| Genesis | 1.1.2或兼容版本 |
| 目标GPU | AMD Radeon AI PRO R9700 |

代码中的`cuda`设备名是ROCm PyTorch的兼容接口。

## 3. 环境设置

### 3.1 Docker

```bash
docker build -f docker/Dockerfile -t pick-fruit-smolvla:rocm7.2.1 .

docker run --rm -it \
  --network=host \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --group-add render \
  --security-opt seccomp=unconfined \
  --ipc=host \
  --shm-size=8g \
  -v "$PWD":/workspace/Pick-Fruit-By-SmolVLA \
  -w /workspace/Pick-Fruit-By-SmolVLA \
  pick-fruit-smolvla:rocm7.2.1
```

容器中：

```bash
export PYTHON_BIN=/opt/venv/bin/python
export PROJECT_ROOT=/workspace/Pick-Fruit-By-SmolVLA
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME=/workspace/huggingface_cache
export HSA_ENABLE_SDMA=0
```

Dockerfile固定ROCm、PyTorch、Triton和LeRobot版本。当前精简提交未包含`uv.lock`，基础Python依赖会在构建时由`pyproject.toml`解析；生成并验证锁文件是正式发布前待办。

### 3.2 已有ROCm环境

```bash
export PROJECT_ROOT="$PWD"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHON_BIN=/path/to/rocm/python
export HF_HOME=/path/to/huggingface_cache
export HSA_ENABLE_SDMA=0
```

如缓存完整，可使用：

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

## 4. 获取数据和权重

外部制品清单位于`artifacts/manifest.json`。下载后应形成：

```text
artifacts/datasets/fruit_pick_dr_600ep/
artifacts/models/smolvla_fruit_pick_dr_600ep/
artifacts/models/plum_residual_sac_lift/last.pt
```

正式发布前必须填写manifest中的下载URL。若URL仍为`null`，表示当前Git仓库只能核查材料和精简结果，不能独立执行模型评估。

检查制品：

```bash
test -f artifacts/datasets/fruit_pick_dr_600ep/meta/info.json
test -f artifacts/models/smolvla_fruit_pick_dr_600ep/config.json
test -f artifacts/models/smolvla_fruit_pick_dr_600ep/model.safetensors
test -f artifacts/models/plum_residual_sac_lift/last.pt

sha256sum artifacts/models/smolvla_fruit_pick_dr_600ep/model.safetensors
sha256sum artifacts/models/plum_residual_sac_lift/last.pt
```

期望SHA256见manifest。

## 5. 不需要权重的检查

### 5.1 Python语法

```bash
"$PYTHON_BIN" -m compileall -q franka_fruit_pick optimization
```

### 5.2 汇总已有runtime结果

先复制一份，避免修改提交结果：

```bash
mkdir -p reproductions/runtime_summary
cp results/runtime/*.json reproductions/runtime_summary/

"$PYTHON_BIN" -m optimization.runtime.summarize_results \
  --results-dir reproductions/runtime_summary
```

期望生成`summary.csv`和`summary.md`，并得到：

| 后端 | Mean | 加速 | 正确性 |
|---|---:|---:|---|
| Eager | 153.81 ms | 1.000× | 基准 |
| HIP Graph | 102.76 ms | 1.497× | 零误差通过 |
| Targeted compile | 63.86 ms | 2.409× | 数值不匹配 |

### 5.3 查看闭环和Residual结果

```bash
sed -n '1,120p' results/closed_loop/hip_graph/summary_100ep.md
sed -n '1,120p' results/closed_loop/targeted_compile/summary_100ep.md
python -c 'import json; d=json.load(open("results/residual_rl/lift_no_gate_100ep.json")); print(d["baseline_success"], d["residual_success"])'
```

## 6. 检查AMD GPU与依赖

```bash
"$PYTHON_BIN" - <<'PY'
import torch
print("torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("GPU:", torch.cuda.get_device_name(0))
assert torch.version.hip is not None
assert torch.cuda.is_available()
PY
```

```bash
"$PYTHON_BIN" - <<'PY'
import genesis, lerobot, torch, torchvision, triton
print("genesis:", genesis.__version__)
print("lerobot:", getattr(lerobot, "__version__", "unknown"))
print("torch:", torch.__version__)
print("torchvision:", torchvision.__version__)
print("triton:", triton.__version__)
PY
```

## 7. 场景Smoke Test

场景资产已包含在仓库中：

```bash
xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" franka_fruit_pick/build_scene.py \
  --steps 50 \
  --save-frames
```

此步骤不需要训练数据或权重。

## 8. 单回合HIP Graph闭环

```bash
mkdir -p reproductions/smoke

xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" franka_fruit_pick/eval_policy.py \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --repo-id demo/fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --episodes 1 \
  --seed 9000 \
  --policy-seed 9000 \
  --pick 011_banana \
  --device cuda \
  --inference-backend hip-graph \
  --hip-graph-capture-warmup 3 \
  --measure-inference \
  --results-out reproductions/smoke/banana_1ep.json
```

单回合只验证链路，不用于判断报告成功率。

## 9. 完整推理测速与正确性

推荐使用仓库入口：

```bash
PYTHON_BIN="$PYTHON_BIN" bash scripts/benchmark_rocm_backends.sh
PYTHON_BIN="$PYTHON_BIN" bash scripts/validate_rocm_backends.sh
```

以下是脚本调用的等价底层命令，便于审计和单独调试：

```bash
export RUNTIME_REPRO=reproductions/runtime_backends
mkdir -p "$RUNTIME_REPRO"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend eager \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_eager.json"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend hip-graph \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_hip-graph.json"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend compile \
  --compile-mode max-autotune-no-cudagraphs \
  --matmul-precision high \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_compile.json"
```

严格验证：

```bash
"$PYTHON_BIN" -m optimization.runtime.validate_full_inference \
  --backend hip-graph \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/validation_hip-graph.json"

"$PYTHON_BIN" -m optimization.runtime.validate_full_inference \
  --backend compile \
  --compile-mode max-autotune-no-cudagraphs \
  --matmul-precision high \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/validation_compile.json"

"$PYTHON_BIN" -m optimization.runtime.summarize_results \
  --results-dir "$RUNTIME_REPRO"
```

预期HIP Graph严格验证通过且固定/变化输入最大误差均为0；Targeted compile预计为`numerical_mismatch`。不要放宽容差将其改写成通过。

## 10. 闭环A/B复现

使用以下脚本分别复现HIP Graph或Targeted Compile闭环A/B；脚本对三类水果依次运行相同seed的Eager与候选后端，并自动调用`summarize_closed_loop_ab.py`：

```bash
# HIP Graph，报告使用seeds 2000–2099
PYTHON_BIN="$PYTHON_BIN" CANDIDATE=hip-graph EPISODES=100 \
  SEED=2000 POLICY_SEED=2000 bash scripts/evaluate_rocm_closed_loop.sh

# Targeted Compile，报告使用seeds 1000–1099
PYTHON_BIN="$PYTHON_BIN" CANDIDATE=targeted-compile EPISODES=100 \
  SEED=1000 POLICY_SEED=1000 bash scripts/evaluate_rocm_closed_loop.sh
```

关键参数：

| 实验 | Seeds | 后端 | Matmul precision |
|---|---|---|---|
| HIP Graph | 2000–2099 | eager / hip-graph | — |
| Targeted compile | 1000–1099 | eager / targeted-compile | highest |

每种水果分别运行100回合：

```text
011_banana
014_lemon
018_plum
```

`eval_policy.py`需要指定同一组`--seed`、`--policy-seed`、`--episodes 100`、`--measure-inference`和独立`--results-out`。完整参考汇总位于`results/closed_loop/`。

## 11. Residual SAC评估

```bash
mkdir -p reproductions/residual_rl

xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" -m franka_fruit_pick.residual_rl.evaluate \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --residual-checkpoint artifacts/models/plum_residual_sac_lift/last.pt \
  --repo-id demo/fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --episodes 100 \
  --seed 2000 \
  --device cuda \
  --jitter 0.03 \
  --arm-scale 0.015 \
  --finger-scale 0.003 \
  --out reproductions/residual_rl/lift_no_gate_100ep.json
```

参考结果是34/100→43/100，但尚未做独立seed验证。

## 12. 重新生成数据与训练

原始已完成训练的核验记录见[历史训练记录](../results/training/README_ZH.md)，其中明确区分checkpoint证明的训练事实、训练期监控指标和固定seed评估结果。

训练数据不在Git仓库中。完整数据生成入口是：

```bash
"$PYTHON_BIN" franka_fruit_pick/record_dataset.py --help
"$PYTHON_BIN" franka_fruit_pick/aggregate_datasets.py --help
```

训练数据为三类水果各200个成功episode，并启用外观、相机、位置姿态、摩擦和质量随机化。

### 12.1 SmolVLA微调

先确认数据集元数据存在：

```bash
test -f artifacts/datasets/fruit_pick_dr_600ep/meta/info.json
```

检查脚本将要执行的LeRobot命令：

```bash
DRY_RUN=1 PYTHON_BIN="$PYTHON_BIN" bash scripts/train_smolvla_fruit_pick.sh
```

开始正式训练：

```bash
PYTHON_BIN="$PYTHON_BIN" bash scripts/train_smolvla_fruit_pick.sh
```

默认`POLICY_PATH=lerobot/smolvla_base`，首次运行需要联网下载。离线运行必须令`HF_HOME`指向完整Hugging Face缓存，或者把`POLICY_PATH`设为本地base/checkpoint目录。两个训练脚本都会生成`<OUTPUT_DIR>.launcher.log`，并将依赖内部打印traceback却返回状态0的情况视为失败。

默认参数与原实验一致：20,000步、batch size 128、seed 1000、每2,000步保存一次。脚本调用`franka_fruit_pick/train_policy.py`，后者再调用LeRobot 0.6.0的`lerobot_train`。预期最终checkpoint为：

```text
reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model/
```

确认输出：

```bash
test -f reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model/model.safetensors
```

完整训练配置快照是`configs/smolvla_train_config.json`。该JSON用于记录实验参数；可执行入口以脚本及其调用的Python程序为准。

### 12.2 Residual SAC训练

该阶段需要数据集以及冻结的SmolVLA checkpoint。默认从`artifacts/models/smolvla_fruit_pick_dr_600ep/`读取，也可以指向12.1生成的模型：

```bash
DRY_RUN=1 PYTHON_BIN="$PYTHON_BIN" \
  POLICY_PATH="$PROJECT_ROOT/reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model" \
  bash scripts/train_residual_sac_lift.sh
```

正式训练：

```bash
PYTHON_BIN="$PYTHON_BIN" \
  POLICY_PATH="$PROJECT_ROOT/reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model" \
  bash scripts/train_residual_sac_lift.sh
```

默认训练100,000步，前10,000步为warmup，batch size 256，task mode为`lift`，每10,000步保存一次。预期输出：

```text
reproductions/rl/plum_residual_sac/checkpoints/last.pt
reproductions/rl/plum_residual_sac/train_metrics.jsonl
```

参数快照见`configs/residual_sac_lift_config.json`。Residual SAC使用仿真特权状态，不属于可直接部署到真实机器人的视觉策略。

原始训练日志共记录361个完成episode、169次训练期成功，最后100个训练episode为45次成功。这些数据来自不断更新策略的训练过程，不能替代第11节固定seed配对评估。

### 12.3 训练后验证

使用第10节的闭环评估命令验证新SmolVLA；使用第11节的配对评估命令验证Residual SAC。重新训练不要求产生逐位相同权重，应比较固定episode集合上的总体成功率和配对翻转统计，而不是单条轨迹。

## 13. 非确定性

Genesis在AMD GPU上跨进程并非逐位确定。即使环境seed和PyTorch seed相同，轨迹和终止步数仍可能变化。因此：

- 不用单回合成功/失败判断复现；
- 比较总体成功率、配对翻转和延迟分布；
- 不要求每个seed轨迹完全一致；
- HIP Graph离线数值验证应保持零误差；
- Targeted compile的严格数值不匹配是已知结果。

## 14. 验收清单

- [ ] 文档、图片和视频链接正常；
- [ ] Python核心源码通过`compileall`；
- [ ] 精简runtime结果能重新生成汇总；
- [ ] `torch.version.hip`非空且AMD GPU可见；
- [ ] manifest中的数据和权重URL可下载且SHA256一致；
- [ ] Genesis场景Smoke Test正常；
- [ ] HIP Graph单回合闭环能产生JSON；
- [ ] HIP Graph严格验证零误差；
- [ ] Targeted compile被标记为数值不匹配；
- [ ] 所有新输出写入`reproductions/`。

## 15. 相关材料

- [中文项目README](../README_ZH.md)
- [中文技术报告](TECHNICAL_REPORT_ZH.md)
- [正式结果](../results/README.md)
- [制品说明](../artifacts/README.md)
- [ROCm runtime](../optimization/runtime/README.md)
- [Residual SAC](../franka_fruit_pick/residual_rl/README.md)
- [历史训练记录](../results/training/README_ZH.md)
- [英文旁白成功与失败分析视频](video/smolvla_success_failure_demo.mp4)
- [视频重建说明](video/NARRATION_EN.md)
