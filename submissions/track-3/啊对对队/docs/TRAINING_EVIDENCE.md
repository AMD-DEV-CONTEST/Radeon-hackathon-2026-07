# Training Evidence / 训练证据

This page records one completed, auditable SmolVLA training run on one AMD Radeon GPU. The evidence is limited to the saved training log, checkpoint metadata, and offline action evaluation.

本页记录一次在单张 AMD Radeon GPU 上完成且可审计的 SmolVLA 训练。证据范围仅包括训练日志、检查点元数据和离线动作评估。

## Evidence Map / 证据索引

| Item / 项目 | Local evidence / 本地证据 | Recorded fact / 已记录事实 |
| --- | --- | --- |
| Runtime / 运行环境 | [`pash-primitive-smolvla-rocm-2800step-v1.json`](../evidence/training/pash-primitive-smolvla-rocm-2800step-v1.json) | AMD Radeon Graphics; ROCm 7.2.53211; PyTorch 2.9.1 ROCm; LeRobot 0.6.1 |
| Dataset audit / 数据审计 | [`pash-primitive-dataset-v2-audit.json`](../evidence/training/pash-primitive-dataset-v2-audit.json) | passed; 7 episodes; 4,557 frames; 43-D state; 20-D action |
| Full training log / 完整训练日志 | [`pash-primitive-smolvla-rocm-2800step-v1.log`](../evidence/training/pash-primitive-smolvla-rocm-2800step-v1.log) | 2,800 logged updates on one GPU |
| Run summary / 运行摘要 | [`pash-primitive-smolvla-rocm-2800step-v1.json`](../evidence/training/pash-primitive-smolvla-rocm-2800step-v1.json) | hashes, throughput, memory, losses and checkpoint metadata |
| Training curve / 训练曲线 | [`pash-primitive-smolvla-2800step-training-curve-v1.png`](assets/pash-primitive-smolvla-2800step-training-curve-v1.png) | generated from the submitted log; single run, `n=1` |
| Offline ablation / 离线消融 | [`pash-primitive-smolvla-2800step-offline-ablation-v1.json`](../evidence/training/pash-primitive-smolvla-2800step-offline-ablation-v1.json) | 42 episode-stage samples; action-contract metrics only |

## Recorded Run / 已记录训练

![SmolVLA training loss / SmolVLA 训练损失](assets/training_loss.png)

| Metric / 指标 | Value / 数值 |
| --- | ---: |
| Updates / 更新步数 | 2,800 |
| Batch size / 批大小 | 8 |
| Workers / 数据线程 | 4 |
| AMP | enabled / 开启 |
| Learnable parameters / 可训练参数 | 99,896,352 |
| Total parameters / 总参数 | 450,061,536 |
| Elapsed time / 用时 | 442 s |
| Mean throughput / 平均吞吐 | 6.33 steps/s |
| Reported peak GPU memory / 日志峰值显存 | 2.32 GB |
| First loss / 首个 loss | 2.164 |
| Final loss / 最终 loss | 0.056 |
| First-100 mean loss / 前 100 步均值 | 1.57606 |
| Last-100 mean loss / 后 100 步均值 | 0.07332 |
| Maximum gradient norm / 最大梯度范数 | 15.566 |

![SmolVLA training curve from the submitted log / 由提交日志生成的 SmolVLA 训练曲线](assets/pash-primitive-smolvla-2800step-training-curve-v1.png)

The loss reduction proves that optimization ran and fitted the submitted training distribution. It does **not** prove task completion. Strict pure-VLA closed-loop evaluation remained **0/3**.

Loss 下降证明训练确实执行并拟合了提交的数据分布，但**不能**证明机器人完成任务。严格纯 VLA 闭环评估仍为 **0/3**。

## Input Contract / 输入合约

The policy uses `observation.state` and `observation.images.overhead_rgb`. The state is 43-D, the action is 20-D, and privileged simulator state is excluded from policy input. The training manifest records 24 primitive task texts. The repository publishes the evidence needed to audit this run without bundling the checkpoint or the original training payload.

策略输入为 `observation.state` 与 `observation.images.overhead_rgb`，状态 43 维、动作 20 维，策略不读取仿真特权状态。数据集含 24 条 primitive 任务文本。数据集二进制和 checkpoint 目前仍在远程训练工作区，公开链接待上传后回填。

## TensorBoard Import Boundary / TensorBoard 导入口径

TensorBoard was not the authoritative training-time tracker for this run. After training, the saved 2,800-update text log was converted into TensorBoard event files with [`import_training_log_to_tensorboard.py`](assets/import_training_log_to_tensorboard.py). The screenshot below is the resulting TensorBoard view; it is evidence that the recorded log can be inspected in TensorBoard, not a claim of native training-time telemetry. The [import manifest](../evidence/training/tensorboard-import-v1/import_manifest.json) records the source log and conversion boundary.

本次运行没有把 TensorBoard 作为训练时的权威记录工具。训练结束后，仓库使用 [`import_training_log_to_tensorboard.py`](assets/import_training_log_to_tensorboard.py) 将保存的 2,800-update 文本日志转换为 TensorBoard event 文件。下图是导入后的真实 TensorBoard 页面，用来说明日志可以在 TensorBoard 中复核，不代表训练期间已实时接入 TensorBoard。[导入清单](../evidence/training/tensorboard-import-v1/import_manifest.json) 记录了源日志和转换口径。

![TensorBoard view imported after training from the recorded text log](assets/tensorboard_log_import.png)

```bash
python3 docs/assets/generate_training_evidence_figures.py --repo-root .
```

## Limitations / 局限

- One training run (`n=1`); no variance or confidence interval is claimed. / 仅一次训练（`n=1`），不报告虚构方差或置信区间。
- Seven episodes are insufficient for broad generalization. / 7 个回合不足以支撑广泛泛化结论。
- Training loss and offline action error are not closed-loop success. / 训练 loss 与离线动作误差不等于闭环成功率。
- No public checkpoint or complete public dataset is available yet. / 目前尚无公开 checkpoint 或完整公开数据集。
