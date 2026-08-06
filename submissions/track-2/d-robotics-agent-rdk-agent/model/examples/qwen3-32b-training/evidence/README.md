# Evidence boundary

主树只保留评委快速核验所需的训练证据：

- `training-summary.json`：模型、数据、LoRA、119-step 训练、Radeon 环境、峰值显存、validation 曲线和 adapter 哈希的紧凑索引；
- `validations/`：step 0/30/60/90/119 五个原始 validation 结果；
- `checkpoint-000119/`：最终 checkpoint 的完成标记及二进制大小/SHA-256 清单。

原始 plan、preflight gates、launch bindings、Phase 1/2 controller 报告、checkpoint-000010、完整 run manifest 与本地总账固定在 Git tag [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training)。该 tag 指向 commit `c079855dabb11e50f7026b9da60e5b162e8f04d2`，因此后续删除 commit、PR squash 或分支清理不会影响归档入口。

这里的清单不包含 adapter、optimizer、RNG 或完整 checkpoint 二进制；公开 adapter 由 `model/SHA256SUMS` 和 ModelScope 下载地址承接。训练证据证明固定代码在原 Radeon 主机上完成训练，不能替代 Agent/板端/物理效果证据。
