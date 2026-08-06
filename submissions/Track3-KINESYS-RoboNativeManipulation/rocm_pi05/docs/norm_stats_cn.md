# 归一化统计（norm_stats）

π05 在训练与推理时，会对本体感知状态（state）输入与动作（action）目标做归一化。归一化统计量在**训练数据**上计算，与 checkpoint 存在一起，推理时原样加载。本仓库的归一化统计由根目录的自包含脚本 `compute_norm_stats.py` 计算，**纯命令行，无需改动 `src/openpi/training/config.py`**。

## 计算

```bash
python3 compute_norm_stats.py \
    --data-dir /path/to/lerobot_dataset \
    --output-dir ./assets/<dataset_name>
```

- 只需 `--data-dir`（本地 LeRobot Dataset v3.0 目录，含 `meta/`、`data/`）与 `--output-dir`。
- 通过 lerobot 接口**离线读 parquet 的 state / action 两列，不解码视频**，逐帧、全表计算 `mean / std / q01 / q99`。
- `--state-source`（默认 `observation.state`）与 `--action-source`（默认 `action`）可在数据集列名不同时覆盖。
- 产物：`./assets/<dataset_name>/norm_stats.json`，键为 `state` 与 `actions`，各自是按**机器人真实维度**的 `mean / std / q01 / q99` 数组。

## 关键约束

- **归一化在零填充（pad）到 `--model-action-dim`（默认 32）之前进行**，因此 `norm_stats.json` 的维度是机器人真实 action 维度（如 BiGym 的 16），不是填充后的 32。
- **训练与推理必须用同一份 norm_stats**。`train_jax.py --norm-stats ./assets/<dataset_name>` 训出的 checkpoint，会把该 `norm_stats.json` 一并存进 `checkpoints/<config>/<exp>/<step>/assets/<asset_id>/`；`inference_server.py` 从 `--checkpoint-dir` 自动加载它，无需另行指定。
- 数据集变更（新增/删除 episode、改 action 维度）后需重算，否则训练/推理的归一化与数据分布不匹配。
- 训练 `Pi0Config` 的 `action_dim` / `action_horizon` / 相机顺序等必须与推理一致；归一化只负责 state/action 的尺度，不替代这些一致性要求（见 [README](../README.md) §功能一/功能二）。

## 流程位置

完整训练/推理流程见 [README](../README.md)（第 1 步算统计 → 第 2 步训练 → 第 3 步推理）与 [`amd_rocm_jax.md`](amd_rocm_jax.md) §2.2。
