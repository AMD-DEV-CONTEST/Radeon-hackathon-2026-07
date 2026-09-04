# 本地多模态模型兼容性决策

## 当前候选

1. 首选：`Qwen/Qwen3-VL-8B-Instruct`
2. 降级：`Qwen/Qwen2.5-VL-7B-Instruct`

“vLLM 支持模型架构”和“vLLM 支持某类 AMD GPU”并不能证明两者在当前 Radeon Cloud 镜像中的组合已经验证。因此最终选择只由实例内冒烟测试决定。

## 当前结论

`Qwen/Qwen3-VL-8B-Instruct` 已于 2026-07-28 在兼容性门内通过，保留为主模型。

- 第一次启动失败：未设置 RDNA 开关时，FlashAttention 误导入
  `flash_attn_2_cuda`；
- 修复：设置镜像已支持的 `FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE`；
- 第二次启动：日志确认 ViT 使用 RDNA Triton Flash Attention，文本与
  多模态测试全部通过；
- 模型权重：17 GB，四个 safetensors 分片完整；
- 不需要下载或切换 Qwen2.5-VL。

## Qwen3-VL 进入条件

- GPU 被 `amd-smi` 与 `rocminfo` 识别；
- PyTorch 使用 ROCm，且可分配 GPU tensor；
- vLLM 版本不低于 Qwen3-VL recipe 的最低要求；
- 服务绑定 `127.0.0.1:8000`；
- `/v1/models`、文本、单图 JSON、八帧时序测试全部通过；
- 无 OOM、进程退出或 JSON 严重不稳定。

## 四小时门

第一次实际启动 Qwen3-VL 前运行：

```bash
python3 scripts/model_gate.py start
```

所有测试通过后记录：

```bash
python3 scripts/model_gate.py record --result pass --reason "all smoke tests passed"
```

失败必须保留真实原因：

```bash
python3 scripts/model_gate.py record --result fail --reason "<错误摘要>"
```

检查是否超时：

```bash
python3 scripts/model_gate.py status
```

从首次尝试起达到四小时仍未通过时，不继续修复 Qwen3-VL，改用 Qwen2.5-VL-7B 并重新执行同一套测试。

## 不采用的捷径

- 不用公共 Qwen/DeepSeek API 替代本地推理；
- 不因为模型能下载就判定兼容；
- 不在缺少公平基线时宣称性能提升；
- 不在第一阶段引入 AWQ/GPTQ/FP8 量化变量。
