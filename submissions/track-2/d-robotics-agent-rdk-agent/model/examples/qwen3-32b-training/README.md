# Qwen3-32B Agentic LoRA-SFT（评委精简版）

这里保留 Radeon 训练的核心代码、运行环境、五个 validation 点、最终 checkpoint 清单和一份紧凑训练摘要。历史 plan、preflight、launch/controller 报告与完整 run manifest 已从主树移出，避免评委先看到大批机器 JSON。

完整原始证据没有丢失，固定在 [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training)（commit `c079855dabb11e50f7026b9da60e5b162e8f04d2`）。

## 一分钟核验

```bash
python3 verify_subset.py
```

该命令只用 Python 标准库，核对当前精简树的文件哈希、Test 行数与 SHA-256；无需 GPU、权重或网络。训练结果先看 [`evidence/training-summary.json`](evidence/training-summary.json)。

## 训练结论

- 基础模型：`unsloth/Qwen3-32B-bnb-4bit@7f721e74a6a8cc9ee352f7e49303a2c1705f9083`
- 方法：4-bit NF4 base + LoRA-SFT（r=8、alpha=16、67,108,864 可训练参数），assistant-only shifted CE
- 1 epoch、119 optimizer steps、948 training micro-windows、最大窗口 8192 tokens
- validation mean CE：1.151614（step 0）→ 0.593663（step 119）
- 最终 adapter：268,555,264 bytes，SHA-256 `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf`
- 单卡 AMD Radeon gfx1100；Phase 2 记录的 PyTorch 峰值为 37,633,069,056 allocated / 38,593,888,256 reserved bytes

## 主树保留什么

| 内容 | 位置 | 用途 |
|---|---|---|
| trainer、controller、gate 与构建工具 | `configs/`、`gates/`、`tools/` | 展示实际训练实现 |
| 固定模型 revision 与运行环境 | `artifacts/model-acquisition/`、`environment/` | 说明 Radeon/ROCm 与依赖口径 |
| 训练摘要与学习曲线 | `evidence/training-summary.json`、`evidence/validations/` | 快速审计 119-step 结果 |
| 最终 checkpoint 清单 | `evidence/checkpoint-000119/` | 绑定发布 adapter 的大小和哈希 |
| 公开 Test | `../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl` | 独立重算 Base/SFT A/B |

训练时的 946-row train 与 116-row validation 已以脱敏形式发布到 [ModelScope](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/summary)。评测时 historically held-out 的 113-row Test 在评测完成后随仓库公开，仅用于复现本次结果。

## 复现口径

公开 adapter 是 demo 与 A/B 使用的制品；下载和服务接口见 [`../../model/README.md`](../../model/README.md) 与 [`../../model/serving/README.md`](../../model/serving/README.md)。完整重训是可选项，数值可能随硬件和软件版本变化。

`configs/` 中是历史训练原件，包含 bound-host fail-closed 门禁，不是跨机器即插即用脚本。换机器时应重新生成 plan、模型验证清单和主机门禁；`tools/build_qwen3_32b_train_plan.py` 与 `tools/build_qwen3_32b_loss_window_plan_v2.py` 提供 plan 构建逻辑，运行合同见 [`docs/RUNBOOK.md`](docs/RUNBOOK.md)。不要把归档中的历史 PASS 当成新主机授权。

## 证据边界

validation CE 下降证明训练发生并收敛；Agentic 能力增益由单独的 Base/SFT A/B 原始输出证明。二者都不等于 `rdk-agent → sophonctl → RDK` 的实时板端执行或物理效果，后者必须由当次演示证据确认。
