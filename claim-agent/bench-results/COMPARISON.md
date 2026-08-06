# AMD GPU 推理后端性能压测对比

> **测试环境**: AMD Radeon Pro W7900 (gfx1100, 48GB VRAM) · ROCm 7.2.4 · Ubuntu 24.04  
> **测试日期**: 2026-07-28  
> **测试工具**: bench.py (OpenAI 兼容 API 基准)

---

## 被测系统

| 项目 | llama.cpp | vLLM |
|------|-----------|------|
| 引擎版本 | llama-server (HIP/ROCm) | vLLM 0.26.0+rocm723 |
| 模型 | Qwen3.6-27B-UD-Q8_K_XL.gguf | Qwen3.6-27B-Quark-W8A8-INT8 |
| 量化 | Q8_0 (8-bit 权重) | W8A8 INT8 (权重+激活 INT8) |
| 视觉编码器 | mmproj-BF16.gguf | 内置 ViT (BF16) |
| dtype | 自动 | float16 |
| 上下文窗口 | 8192 | 4096 |
| MTP 推测解码 | ❌ | ❌ (0% acceptance on quantized model, disabled) |
| KV Cache | FP16 | FP16 (no FP8 HW on RDNA3) |
| 显存占用 | ~35 GB | ~29 GB (权重 28.5G + KV) |

---

## 一、串行文本基准

### max_tokens = 64

| 指标 | llama.cpp | vLLM |
|------|:---------:|:----:|
| avg_TTFT | 0.23s | 0.17s |
| avg_总耗时 | 1.79s | 5.31s |
| avg_吞吐 | **41.0 tok/s** | 12.5 tok/s |

### max_tokens = 128

| 指标 | llama.cpp | vLLM |
|------|:---------:|:----:|
| avg_TTFT | 11.53s | **0.17s** |
| avg_总耗时 | 14.59s | **10.55s** |
| avg_吞吐 | **41.9 tok/s** | 12.3 tok/s |

#### llama.cpp max_tokens=128 详细

| # | TTFT | 总耗时 | 解码吞吐 |
|---|-----:|------:|--------:|
| 1 | 0.10s | 3.11s | 42.5 tok/s |
| 2 | 14.17s | 17.25s | 41.6 tok/s |
| 3 | 14.32s | 17.30s | 42.9 tok/s |
| 4 | 14.12s | 17.19s | 41.7 tok/s |
| 5 | 14.95s | 18.08s | 40.9 tok/s |

#### vLLM max_tokens=128 详细（优化后：float16 KV + enforce-eager + v0.26.0）

| # | TTFT | 总耗时 | 解码吞吐 |
|---|-----:|------:|--------:|
| 1 | 0.17s | 10.54s | 12.3 tok/s |
| 2 | 0.17s | 10.55s | 12.3 tok/s |
| 3 | 0.17s | 10.57s | 12.3 tok/s |

### max_tokens = 512

| 指标 | llama.cpp | vLLM |
|------|:---------:|:----:|
| avg_TTFT | 3.30s | **0.18s** |
| avg_总耗时 | 17.39s | 43.15s |
| avg_吞吐 | **35.4 tok/s** | 11.9 tok/s |

---

## 二、并发压测 (max_tokens=128, continuous batching)

| 并发数 | llama.cpp 吞吐 | 加速比 | vLLM 吞吐 | 加速比 | vLLM vs llama |
|:------:|:-------------:|:------:|:---------:|:------:|:-------------:|
| 1 | 10.0 tok/s | 1.00x | 11.4 tok/s | 1.00x | 1.14x |
| 2 | 16.3 tok/s | 1.63x | 21.9 tok/s | 1.92x | 1.34x |
| 4 | 20.6 tok/s | 2.06x | 45.0 tok/s | 3.95x | **2.18x** |
| 8 | 21.9 tok/s | 2.19x | 82.1 tok/s | 7.20x | **3.75x** |

```text
聚合吞吐 (tok/s) 随并发数变化:

  vLLM:     ████████████████████████████████████████████████████████████████████████████ (82)
  llama.cpp:█████████████████▌ (22)
```

---

## 三、Prefill 不同上下文 TTFT

| 上下文长度 | llama.cpp | vLLM | vLLM 优势 |
|:---------:|:---------:|:----:|:--------:|
| 128 tok | 0.61s | **0.20s** | 3.1x |
| 512 tok | 1.58s | **0.66s** | 2.4x |
| 1024 tok | 2.96s | **1.27s** | 2.3x |
| 2048 tok | 11.58s | **3.50s** | 3.3x |

> vLLM 的 chunked-prefill 使 prefill 性能大幅领先

---

## 四、多模态 OCR 延迟

| 后端 | 端到端耗时 | 备注 |
|------|:--------:|------|
| llama.cpp | **2.87s** | |
| vLLM | 8.11s | 含 thinking 输出干扰 |

---

## 五、综合结论

### llama.cpp 优势

- **单请求解码吞吐**: 41 tok/s vs 12 tok/s（~3.4x 更快）
- **多模态 OCR**: 2.87s vs 8.11s（~2.8x 更快）
- **显存占用更低**: ~35 GB vs ~29 GB（vLLM 权重为 INT8）
- **部署简单**: 单二进制，无需 Python 环境
- 适合：单用户、低并发、批处理场景

### vLLM 优势

- **TTFT 稳定且极低**: 0.17s 恒定，llama.cpp 波动 0~15s（68x 改善）
- **并发近线性扩展**: C8=82.1 tok/s vs llama.cpp 21.9 tok/s（3.75x）
- **长上下文 prefill 快**: 2048 tok TTFT 3.50s vs 11.58s（3.3x）
- **vLLM 优化 (2026-08-03)**: 杀掉 FP8 KV 模拟（RDNA 无 FP8 核）+ 升级 0.26.0 → 单请求 9.0→12.3 tok/s (+37%)；MTP/CUDA-Graph 在 RDNA 上均实测为负优化
- **Continuous Batching**: 聚合效率远优于 llama.cpp 的 static batching
- 适合：多用户 API 服务、高并发、长文档场景

### 当前环境选择

本部署采用的是 **llama.cpp**（GGUF Q8_K_XL），原因：
- 项目为单人使用，无并发压力
- 多模态 OCR 是核心功能，llama.cpp 更优
- 可同时保留 vLLM INT8 模型用于未来多用户场景

---

## 文件索引

| 文件 | 内容 |
|------|------|
| `bench-results/serial_128.json` | llama.cpp 串行基准 |
| `bench-results/concurrency.json` | llama.cpp 并发数据 |
| `bench-results/vision_ocr.json` | llama.cpp 多模态延迟 |
| `bench-results/prefill.json` | llama.cpp prefill TTFT |
| `bench-results/vllm/serial_128.json` | vLLM 串行基准 |
| `bench-results/vllm/concurrency.json` | vLLM 并发数据 |
| `bench-results/vllm/vision_ocr.json` | vLLM 多模态延迟 |
| `bench-results/vllm/prefill.json` | vLLM prefill TTFT |
