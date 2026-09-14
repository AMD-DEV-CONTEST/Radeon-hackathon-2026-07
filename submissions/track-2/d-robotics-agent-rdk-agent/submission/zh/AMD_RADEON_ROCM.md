# AMD Radeon 与 ROCm 部署及优化指南

## 合规目标

团队已实际跑通两条私有 Radeon 推理路径：自训练的 Qwen3 32B SFT 路径，以及 Qwen3-Next 80B 单 GPU 服务路径。两条路径均运行在参赛者控制的 `gfx1100` 主机上，并保留了可审计的实测记录。另有一个 `rdk-agent` 客户端配置路由到私有 OpenAI-compatible vLLM 端点；公开的 80B 性能数字不使用该端点的服务器来源信息。

## 当前客户端配置

私有开发环境当前选择：

| 字段 | 值 |
| --- | --- |
| Pi provider | `amd` |
| 模型 | `Qwen3-Next-80B-A3B-Instruct` |
| API 形式 | OpenAI-compatible Chat Completions |
| 声明的上下文窗口 | 131,072 tokens |
| 声明的最大输出 | 8,192 tokens |

端点和 API key 被有意排除。公开示例通过环境变量读取密钥：[pi-models.amd-rocm.example.json](config/pi-models.amd-rocm.example.json)。

该客户端配置只能证明模型路由，不能证明 GPU 型号、ROCm 版本、服务后端或量化方式。

## 当前证据范围

已封存证据包括：

1. **32B SFT：** `gfx1100`、ROCm 7.2.1/HIP 身份、固定的基座 revision 与 adapter 哈希、NF4 4-bit 配置、`/v1/models`、每臂 88 次 A/B，以及五节点 `rdk-agent` 实机截图。
2. **80B：** `gfx1100`、Q4_K_M GGUF 身份与哈希、单卡显存证据、十条基线/优化记录、聚合验证脚本，以及三项 API 兼容性 canary。
3. **私有 vLLM 客户端路由：** provider `amd` 与模型选择已经验证，但其独立服务器的 GPU、ROCm/vLLM 版本、启动命令、revision 与精度未在此单独封存。

详见 [MODEL_TRACK.md](MODEL_TRACK.md)、[`model/AGENT_E2E.md`](../../model/AGENT_E2E.md)与根 README 第 9.5 节。

## 已实现的软件层推理控制

- 确定性的问候/确认回复旁路。
- 采用不启用工具、不加载 Skill、无上下文的小型意图分类会话。
- 各阶段使用聚焦会话，避免单个会话无限增长。
- 严格加载 Skill，并提供明确的选择证据。
- 文本交接限制在 6,000 个字符以内。
- 在模型外执行确定性的结构与安全检查。
- 以文件作为各阶段之间持久化的事实来源。

这些特性可以减少不必要的 token 消耗和上下文增长，但不能替代经测量的 GPU 优化。

## 受控优化矩阵

保持提示词、输出上限、软件 revision 和正确性标准不变；每次只改变一个变量。

| 实验 | 基线 | 候选配置 | 所需证据 |
| --- | --- | --- | --- |
| 精度/量化 | 服务器默认值 | 硬件支持的较低精度或量化模型 | 确切启动参数、VRAM、正确性、TTFT、tokens/s |
| 上下文上限 | 支持的最大值 | 限制为工作流实测所需大小 | 输入 token 数、截断检查、延迟、VRAM |
| 模型预热 | 冷进程 | 采用有记录预热流程的热进程 | 冷/热样本、p50/p95 |
| 内存利用率 | 服务器默认值 | 调优后的 vLLM 利用率 | 多次运行无 OOM、峰值 VRAM |
| 并发度 | 单请求 | 经测量的低并发 | 单请求延迟与吞吐量 |
| 提示词负载 | 完整通用上下文 | 限定智能体 + 已选 Skill | token 数、阶段正确性、端到端时间 |

## 指标

- 客户端首 token 时间（TTFT）的 p50 和 p95。
- 解码输出速度（tokens/s）。
- 请求总延迟。
- 端到端工作流耗时。
- 峰值 VRAM 与 GPU 利用率。
- 仅当目标环境提供可靠计数器时，记录功率或能耗。
- 使用相同提示词时的正确响应率与验收通过率。

## 基准测试命令

```sh
node submission/zh/scripts/benchmark-openai-compatible.mjs \
  --provider amd \
  --runs 10 \
  --output submission/zh/evidence/amd-endpoint-benchmark.json
```

为便于追踪，报告包含端点 host，但不包含 scheme、path 或 key。如果 host 也会暴露私有基础设施，请将其删除或哈希化。

## 证据表

| 项目 | 32B SFT 路径 | 80B 服务路径 |
| --- | --- | --- |
| 客户端/API 身份 | 已封存 `/v1/models` 与 `/health` | 已封存三项 API 兼容性 canary |
| AMD Radeon GPU | `gfx1100`，51.5 GB | `gfx1100`，51.5 GB |
| ROCm/运行时 | ROCm 7.2.1，torch 2.9.1+rocm7.2.0 | 已封存 `llama.cpp` HIP 二进制；未采集确切 ROCm 版本 |
| 精度/量化 | NF4 4-bit 基座 + LoRA，bf16 计算 | Q4_K_M GGUF |
| 基线 -> 优化 TTFT | p50 17.41 -> 8.26 s；p95 83.97 -> 12.89 s | 已封存中位数 2,021.26 -> 1,808.76 ms |
| 基线 -> 优化解码 | 6.54 -> 6.72 tok/s | 37.19 -> 49.82 tok/s |
| 峰值显存 | 27.99 -> 28.06 GB | 48.84 -> 49.52 GB |
| Agent 工作流 | 4 分 04 秒完成 5/5 节点 | 未单独封存五节点轨迹 |

独立私有 vLLM 服务器仍只是一项客户端路由声明。任何未测量值都不会被描述为实测。
