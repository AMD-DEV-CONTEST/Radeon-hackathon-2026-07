# Radeon 与 ROCm 本地推理

比赛正式模式使用 AMD Radeon GPU、ROCm、vLLM 和 `Qwen/Qwen2.5-7B-Instruct`。PrivateOps 与模型服务运行在同一个 Radeon Cloud 实例中，符合要求的地址只能是同实例回环接口 `http://127.0.0.1:8000/v1/chat/completions`。

已采集环境为 AMD Radeon Graphics、`gfx1100`、ROCm 7.2.1、带 HIP 的 PyTorch 2.9.1 和 vLLM 0.16.1。`rocm-local` 会拒绝远程模型端点，失败时不会静默降级。AMD 共享 HTTPS API 只用于开发辅助，不作为比赛核心推理证明。
