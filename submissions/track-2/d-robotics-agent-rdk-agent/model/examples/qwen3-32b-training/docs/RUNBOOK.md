# Formal training runbook

## 1. 适用范围

本 runbook 只描述已经验证的 `Qwen3-32B-bnb-4bit` 单卡 48 GB AMD 路径。核心源码保持原字节，不在本目录中“泛化”硬件、数据或超参数。

正式布局：

```text
/workspace/qwen36-agentic-sft/
├── .venv/
├── configs/
├── artifacts/training-plan/
├── artifacts/model-acquisition/
├── data/rdk-sft-v1-20260803-agentic/
├── models/Qwen3-32B-bnb-4bit-7f721e74/
└── runs/<fresh-run-id>/
```

## 2. 冻结训练合同

- QLoRA：rank 8、alpha 16、dropout 0，目标为 q/k/v/o 与 gate/up/down projections
- base compute：BF16；LoRA 与 AdamW state：FP32
- assistant-only shifted CE；每个 optimizer step 按冻结 supervised-token 总量归一化
- max 8192 tokens；不 packing、不 padding；长样本使用冻结语义边界窗口和绝对 position IDs
- 119 steps；validation 发生在 0/30/60/90/119
- checkpoint 发生在 10/20/.../110/119
- 每个 micro backward 后执行 `synchronize -> gc.collect -> empty_cache`
- Controller 以 250 ms 采样，GPU 硬线 44 GiB，CPU 硬线 48 GiB

## 3. Phase 1 / Phase 2 语义

Phase 1 必须是全新 run，不允许 `--resume`。它在发布不可变 `checkpoint-000010` 后以 `exit 75` 退出；Controller 应判定 `PASS / RESTART_READY`。

Phase 2 必须是全新进程，只允许：

```text
--resume <same-run>/checkpoints/checkpoint-000010
```

Trainer 会在 GPU runtime 初始化后逐项重验 adapter、optimizer、RNG、state、manifest、Phase 1 process identity，并原子发布 `resume-ack-phase2.json`。Phase 2 正常终态为 `exit 0 / PASS` 和 `checkpoint-000119/COMPLETE`。

一旦 `resume-ack-phase2.json` 出现，Phase 2 是 one-shot。后续若异常，禁止删除 ack/checkpoint 后原地重跑，必须重新做恢复审计。

## 4. 历史已验证命令

完整 argv 和 13 项环境变量已经原样保存：

- Phase 1：`evidence/launch/launch-binding.json`
- Phase 2：`evidence/launch/phase2-launch-binding.json`

这两份文件是历史命令证明，不是新 run 的 launcher。新的正式 run 必须先完成身份、GPU 空闲、进程防重入、输入哈希与资源检查，并为新的 run ID 签发新的只读 authorization/launch binding。

Controller 的核心装配差异：

| 项目 | Phase 1 | Phase 2 |
|---|---|---|
| controller run dir | `<run>/phase1-controller` | `<run>/phase2-controller` |
| expected exit | `75` | `0` |
| expected result | `RESTART_READY` | `PASS` |
| trainer phase | `phase1` | `phase2` |
| resume | 禁止 | 精确 `checkpoint-000010` |

## 5. 权重补齐和权限

模型目录需补齐四个分片并按 verification JSON 逐文件重哈希。正式输入应为只读：目录 `0555`，文件 `0444`。Trainer、common、plans、model verification、data、模型文件均不能带写位或软链接。

不要覆盖已发布 run。每次正式训练使用新的安全 run ID；不要使用 `latest` 自动恢复。

## 6. 验证边界

当前 bundle 已证明源码等价、数据/计划合同、正式 Phase 1/2 执行与 checkpoint 发布。重新补权重后，在目标机上的 fresh-launch readiness 仍需独立 preflight；换机器则必须重新冻结整条合同。

