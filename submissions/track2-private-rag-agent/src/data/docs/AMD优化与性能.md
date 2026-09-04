# AMD ROCm 优化与性能报告

## 一、GPU 推理后端选型

本项目针对 AMD Radeon GPU 提供三种推理后端，均基于 ROCm 开源软件栈：

1. **llama.cpp (HIP)**：通过 `CMAKE_ARGS="-DGGML_HIP=ON"` 编译，GGUF 模型可全层 GPU offload。适合单机单卡，延迟最低。
2. **Ollama (ROCm)**：Linux 下自动启用 ROCm 后端，`ollama ps` 可验证模型 100% GPU 加载。开箱即用，适合快速部署。
3. **vLLM (ROCm)**：官方 rocm/vllm 容器镜像，支持高并发批处理，适合 Radeon Cloud 等云端 GPU 场景。

## 二、模型量化优化

GGUF 量化在精度与显存之间取得平衡：

| 量化 | 显存占用 | 推理速度 | 推荐 |
|---|---|---|---|
| Q8_0 | 约 8.2GB | 快 | 追求精度时选用 |
| Q4_K_M | 约 4.6GB | 最快 | 均衡推荐，默认选择 |
| FP16 | 约 16GB | 慢 | 一般不推荐 |

以 7B 级模型为例，Q4_K_M 相比 FP16 可节省约 70% 显存，同时速度提升 2 倍以上，精度损失可接受。

## 三、多 Agent 并行的 GPU 资源节流

多 Agent 并行模式下，每个子 Agent 各自持有检索实例。为避免重复加载模型造成显存浪费，本项目做了三项优化：

1. **模块级单例**：embedding 模型和 cross-encoder 重排模型做全局共享，n 个并行子 Agent 只加载一份，显存开销从 n 倍降到 1 倍。
2. **懒加载**：重排模型在首次检索时才加载，避免启动即占满显存。
3. **并行度可控**：n_workers 可配置，避免线程过多导致 GPU 排队竞争。

## 四、性能验证方法

- `rocminfo` 确认 ROCm 设备可见。
- `rocm-smi` 实时监控 GPU 利用率、显存、温度、功耗。
- `ollama ps` 确认模型是否 100% GPU offload。
- `benchmarks/bench_amd.py` 自动检测环境，输出 tokens/s 与推理耗时对比。

## 五、加速收益

在 AMD Radeon GPU 上，同一套代码相比 CPU 推理吞吐可提升 5~10 倍。多 Agent 并行的动机正是吃满 GPU 的并发能力：本地 GPU 上多个推理并发排队，串行转并行后多步研究任务的墙钟时间大幅下降。
