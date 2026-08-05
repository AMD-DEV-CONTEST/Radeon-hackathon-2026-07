# NeuPAN 的 AMD ROCm 适配说明

本文记录 RadeonNav 中 NeuPAN 的 ROCm 移植范围、配置方法、代码边界、验收结果和
当前限制。这里的“ROCm DUNE”只表示把学习式 DUNE 距离编码器放到 AMD GPU；在线
凸优化 NRMP 仍使用 CPU 上的 CVXPYLayers/ECOS。这是当前推荐的 AMD 混合模式。

## 1. 当前设备划分

| 模块 | 设备 | 实现 |
| --- | --- | --- |
| DUNE/ObsPointNet 前向 | AMD GPU | PyTorch ROCm，配置中的设备名为 `cuda` |
| 点流、旋转和 latent distance 后处理 | CPU | PyTorch FP32 |
| NRMP 参数规范化和凸优化 | CPU | CVXPYLayers + ECOS |
| depth encoder、TSC、BBC | AMD GPU | RadeonNav runner 的 `--device cuda` |
| MuJoCo 刚体动力学和碰撞 | CPU | UniLab/MuJoCo |
| 无头图像渲染 | GPU 图形栈 | EGL；与 NeuPAN DUNE 设备开关相互独立 |

ROCm 版本的 PyTorch 沿用 `torch.cuda` API 和 `cuda` 设备字符串。因此 YAML 中的
`dune_device: cuda` 在这台机器上指向 AMD GPU，并不表示使用 NVIDIA CUDA。

当前验证环境为：

- AMD Radeon Graphics（`gfx1100`）
- AMD EPYC 9334，2 路、64 核/128 线程
- ROCm/HIP 7.2.26015
- PyTorch 2.11.0+rocm7.2
- MuJoCo 3.8.0
- CVXPYLayers CPU backend + ECOS

## 2. 代码改动

适配没有增加自定义 HIP/CUDA kernel，主要改动如下：

- `neupan/blocks/dune.py`
  - 为 DUNE 增加独立的 `inference_device` 和 `inference_dtype`。
  - checkpoint 始终先加载到 CPU，再把模型移动到推理设备。
  - 把整个预测时域的 point flow 合并为一个 batch，在 GPU 上执行一次前向。
  - 将很小的 DUNE 输出显式复制回规划器的 CPU device/dtype，避免
    CVXPYLayers 对 GPU tensor 调用 NumPy。
- `neupan/blocks/pan.py`
  - 将 YAML 的 `pan.dune_device`、`pan.dune_dtype`、`pan.nrmp_backend` 传给 DUNE
    和 NRMP。
- `neupan/blocks/nrmp.py`
  - 默认后端名称显式化为 `cvxpylayers_cpu`。
  - 另有实验性 `mpax_rocm` 后端和安全回退，但它不是本文推荐混合模式的一部分。
- `experiments/neupan_agility/run_dynamic_planner.py` 和 `run_radeon_nav.py`
  - 增加 `--planner-config`。
  - 结果 JSON 记录实际 DUNE device/dtype、NRMP backend/solver/device、配置哈希，
    并将运行时与配置不一致视为验收失败。
- `experiments/neupan_agility/go2_planner_rocm_hybrid.yaml`
  - 保存显式混合配置，不修改历史 CPU-DUNE 默认配置。

## 3. 配置

核心 YAML 如下：

```yaml
device: cpu

pan:
  dune_checkpoint: example/model/go2_diff_070_040/model_2000.pth
  dune_device: cuda
  dune_dtype: float32
  nrmp_backend: cvxpylayers_cpu

adjust:
  solver: ECOS
```

顶层 `device` 必须保持 `cpu`，否则 NRMP/CVXPYLayers 会收到 GPU tensor。当前闭环
基线使用 FP32，以减少跨设备数值差异；DUNE 类支持 FP16/BF16，但尚未把它们作为
RadeonNav 长程验收配置。

## 4. 启动方式

wrapper 提供统一的 `--rocm-dune` 参数：

```bash
cd /workspace/RadeonNav

# NeuPAN tire 单任务，生成录像和 manifest
OUTPUT_DIR=outputs/recordings/neupan-hybrid \
  ./scripts/record_neupan_tire.sh --rocm-dune --rerun

# RadeonNav 完整长程，成功或失败都会保留录像和结果 JSON
OUTPUT_DIR=outputs/radeon-nav/hybrid \
  ./scripts/record_radeon-nav.sh --rocm-dune

# 快速环境、NeuPAN、策略和 full-stack smoke 验收
OUTPUT_DIR=outputs/tests/radeon-nav-hybrid \
  ./scripts/test_radeon-nav.sh --rocm-dune
```

不带 `--rocm-dune` 时仍使用 `go2_planner.yaml` 的 CPU-DUNE 历史基线。高级调试可
用 `PLANNER_CONFIG=/absolute/path/to/planner.yaml` 覆盖默认配置；命令行
`--rocm-dune` 会明确选择仓库内的混合 YAML。

直接 runner 也可以使用同一配置：

```bash
./scripts/run_python.sh experiments/neupan_agility/run_dynamic_planner.py \
  --planner-config experiments/neupan_agility/go2_planner_rocm_hybrid.yaml \
  --layout tire-static --arm neupan --seed 7
```

## 5. 独立数值与性能验收

```bash
./scripts/run_python.sh NeuPAN/example/dune_rocm_smoke.py --iterations 100
./scripts/run_python.sh -m pytest -q \
  NeuPAN/tests experiments/neupan_agility/test_bridge.py
```

本机固定输入测试结果如下。频率按 `1000 / 单次延迟` 换算，只表示 DUNE 前向的
等效吞吐，不是闭环控制调度频率。

| DUNE 设备 | 平均前向耗时 | 等效前向频率 | 相对 CPU |
| --- | ---: | ---: | ---: |
| CPU/FP32 | 约 5.05 ms | 约 198 Hz | 1.00× |
| AMD ROCm GPU/FP32 | 约 0.894 ms | 约 1119 Hz | 约 5.65× |

CPU/GPU 最大绝对误差约 `1.49e-6`，混合 planner action 与 CPU 基线在 `1e-3`
容差内一致。两组 planner 的 NRMP 均为 CPU CVXPYLayers/ECOS；相关测试共 13 项
通过。

## 6. 闭环结果

2026-08-05 在目标 ROCm 机器上的结果：

| 场景 | DUNE / NRMP | 结果 | NeuPAN 延迟 | 说明 |
| --- | --- | --- | --- | --- |
| NeuPAN tire 单任务 | ROCm GPU / CPU ECOS | 通过 | P50 11.16 ms，P95 22.06 ms，P99 23.81 ms | 560 步到达，零碰撞，录像 750 帧 |
| RadeonNav 长程 | ROCm GPU / CPU ECOS | 未通过 | P50 19.83 ms，P95 23.06 ms，P99 24.41 ms | 通过 bar 和第二个转弯后，在 tire 前姿态失稳；重复运行在同一区域复现 |
| RadeonNav 长程对照 | CPU / CPU ECOS | 通过 | P50 22.16 ms，P95 26.61 ms，P99 38.70 ms | 同一 runner、权重和任务参数，到达终点且 upright |

同一 tire 任务还保留了 CPU-DUNE 对照：CPU-DUNE + CPU-NRMP 的 P50/P95 为
11.82/23.85 ms（等效 84.6/41.9 Hz）；ROCm-DUNE + CPU-NRMP 的最新 P50/P95 为
10.93/21.43 ms（等效 91.5/46.7 Hz）。完整 planner 只小幅加速，是因为 CPU
NRMP/ECOS 和数据搬运仍占据单次规划耗时。runner 每 5 个 50 Hz 仿真步调用一次
NeuPAN，因此两种配置在该闭环中的实际调度频率都是 10 Hz，而不是上述延迟倒数。

单步延迟说明 DUNE 上 GPU 没有明显拖慢 NeuPAN，且固定输入前向明显加速；但长程
闭环尚未达到功能等价。DUNE 的约 `1e-6` 输出差异会改变 NRMP 的连续控制量，并在
数千步闭环中逐步放大，因此不能只凭单步误差判定迁移成功。混合配置暂不设为默认。

每次运行都应检查结果 JSON：

```text
checks.neupan_runtime_matches_planner_config
contracts.neupan_runtime.dune_device
contracts.neupan_runtime.nrmp_backend_active
contracts.neupan_runtime.nrmp_solver
contracts.neupan_runtime.hybrid_rocm_dune_cpu_nrmp
```

预期值分别为 `true`、`cuda:0`、`cvxpylayers_cpu`、`ECOS` 和 `true`。

## 7. 与实验性 MPAX 后端的区别

`--rocm-dune` 不会启用 MPAX。它只把小型 DUNE 网络移到 AMD GPU，NRMP 继续走
CPU/ECOS。实验性的 `mpax_rocm` 会把 NRMP QP 交给 JAX/MPAX ROCm，但当前小 QP
存在 CPU 规范化、跨设备复制、无跨调用 warm start 等开销，实测明显慢于 ECOS。
因此 MPAX 仅保留为研究入口，不用于上述单任务或长程基线。

## 8. 当前结论

- NeuPAN 本体的 DUNE ROCm 前向已经可用，并通过固定输入误差、planner action 和
  tire 闭环录像验收。
- CPU NRMP + ROCm DUNE 是当前最合理的 AMD 拆分方案。
- 长程闭环仍对跨设备数值差异敏感；默认配置继续使用 CPU-DUNE，避免破坏已有成功
  基线。
- 后续若要提升为默认，应进行多相位/多初始条件统计，并针对 NRMP 输入、障碍点排序
  和控制输出建立逐步差异追踪，而不是只增加训练轮数。
