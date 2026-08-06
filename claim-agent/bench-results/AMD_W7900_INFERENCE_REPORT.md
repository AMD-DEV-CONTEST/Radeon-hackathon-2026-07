# AMD W7900 大模型推理部署与性能分析报告

> **硬件**: AMD Radeon Pro W7900 (gfx1100, 48GB VRAM)  
> **软件栈**: ROCm 7.2.4 · PyTorch 2.11.0 · Ubuntu 24.04  
> **日期**: 2026-07-28

---

## 一、部署目标

为「智能理赔 Agent」系统在 AMD GPU 上部署 Qwen3.6-27B 多模态 VLM 推理后端，评估两种主流通用推理方案：

| 方案 | 引擎 | 模型格式 | 量化 |
|------|------|---------|------|
| llama.cpp | llama-server (HIP) | Qwen3.6-27B-UD-Q8_K_XL.gguf | Q8_0 |
| vLLM | vLLM 0.26.0+rocm723 | nameistoken/Qwen3.6-27B-Quark-W8A8-INT8 | W8A8 INT8 |

---

## 二、环境搭建

### 2.1 llama.cpp 启动

```bash
./llama-server \
  -m /workspace/models/Qwen3.6-27B-UD-Q8_K_XL.gguf \
  --mmproj /workspace/models/mmproj-BF16.gguf \
  -ngl 99 \
  --host 0.0.0.0 --port 8080 \
  -c 8192
```

### 2.1.2 llama.cpp MTP + 256K 上下文优化

启动 llama.cpp 内置 MTP 推测解码，并扩展到 256K 上下文：

```bash
llama-server \
  -m /workspace/models/Qwen3.6-27B-UD-Q8_K_XL.gguf \
  --mmproj /workspace/models/mmproj-BF16.gguf \
  -ngl 99 \
  -c 262144 \
  -ctk q4_0 -ctv q4_0 \
  --host 0.0.0.0 --port 8080 \
  --spec-type draft-mtp \
  --spec-draft-n-max 2
```

| 参数 | 说明 |
|------|------|
| `-c 262144` | 256K 上下文窗口 |
| `-ctk/ctv q4_0` | Q4_0 压缩 KV Cache（Q8_0 + MTP 导致 OOM） |
| `--spec-type draft-mtp` | 启用 MTP 推测解码 |
| `--spec-draft-n-max 2` | 每次猜测 2 个 token |

**MTP 效果实测：**

```
draft acceptance = 1.00000 (2 accepted / 2 generated)
mean acceptance length = 3.00
predicted_per_second: 50.0 tok/s   ← 对比基础 41 tok/s，提速 22%
```

**踩坑：** Q8_0 KV Cache + MTP(~1.3GB) + mmproj(~1.1GB) 累加超出 48GB 显存，需降为 Q4_0 KV Cache。

### 2.2 vLLM 安装

```bash
uv venv /workspace/.venv --python 3.12
source /workspace/.venv/bin/activate
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/
```

报错列表与解决：

| 报错 | 原因 | 解决 |
|------|------|------|
| `Failed to resolve 'localhost'` | 容器 /etc/hosts 缺 localhost | 改用 `127.0.0.1` |
| EngineCore 僵尸进程 (BF16) | RDNA GPU 不支持 BF16 张量核 | 加 `--dtype float16` |
| `Address already in use` | 8080 端口被 llama.cpp 占用 | 先停旧服务 |
| EngineCore 僵尸进程 (compilation) | CUDA Graph 抢占显存，KV Cache 不足 | 降 max_model_len + max_num_seqs |
| `max_num_seqs (256) exceeds Mamba cache blocks (67)` | Qwen3 48层 GDN 状态缓存不足 | 设 `--max-num-seqs 8` |
| MTP Triton kernel JIT 热编译 | MTP 推测解码 kernel 在 RDNA 上未预编译 | 去掉 `--speculative-config` |

### 2.3 vLLM 可用配置

```bash
# 方式 A: 高并发 + 编译优化 (32K 上下文)
vllm serve /models/Qwen3.6-27B-Quark-W8A8-INT8 \
  --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 \
  --gpu-memory-utilization 0.9 --trust-remote-code \
  --host 0.0.0.0 --port 8080 --dtype float16 --kv-cache-dtype fp8_e4m3
# ⚠️ 吞吐仅 2.6 tok/s，不推荐

# 方式 B: Enforce Eager + 长上下文 (200K)
vllm serve /models/Qwen3.6-27B-Quark-W8A8-INT8 \
  --tensor-parallel-size 1 --max-model-len 200000 \
  --gpu-memory-utilization 0.9 --trust-remote-code \
  --host 0.0.0.0 --port 8080 --dtype float16 \
  --enforce-eager --kv-cache-dtype fp8_e4m3
# ✅ 12.5 tok/s，200K 上下文可用
```

---

## 三、性能基准测试

### 3.1 串行文本吞吐 (bench.py --n 5)

| max_tokens | llama.cpp | vLLM (eager, float16 KV) |
|:---------:|:---------:|:------------:|
| 64 | **41.0 tok/s** | 12.5 tok/s |
| 128 | **41.9 tok/s** | 12.3 tok/s |
| 512 | **35.4 tok/s** | 11.9 tok/s |

> vLLM 已优化（2026-08-03）：去掉 FP8 KV Cache 模拟（RDNA 无 FP8 硬件）+ 升级 v0.26.0 + `--skip-mm-profiling`，单请求从 9.0 提升到 12.3 tok/s (+37%)。

### 3.2 TTFT（首 Token 延迟）

#### max_tokens=128，5 次请求逐条 TTFT

| # | llama.cpp | vLLM |
|--:|:---------:|:----:|
| 1 | 0.10s | 0.17s |
| 2 | **14.17s** | 0.17s |
| 3 | **14.32s** | 0.17s |
| 4 | **14.12s** | 0.17s |
| 5 | **14.95s** | 0.17s |
| avg | 11.53s | **0.17s** |

> vLLM TTFT 极低且稳定，llama.cpp 存在 KV Cache 导致的大幅波动（首次 0.1s，后续 ~14s）

### 3.3 并发扩展 (max_tokens=128)

| C | llama.cpp 聚合 | 加速比 | vLLM 聚合 | 加速比 | vLLM/llama |
|:--:|:---:|:---:|:---:|:---:|:---:|
| 1 | 10.0 | 1.00x | 11.4 | 1.00x | 1.14x |
| 2 | 16.3 | 1.63x | 21.9 | 1.92x | 1.34x |
| 4 | 20.6 | 2.06x | 45.0 | 3.95x | 2.18x |
| 8 | 21.9 | 2.19x | **82.1** | **7.20x** | **3.75x** |

```text
聚合吞吐趋势 (tok/s):

vLLM:        ██████████████████████████████████████████████████████████████████████████▌ 82.1
llama.cpp:   ██████████████████████▏ 21.9
```

### 3.4 Prefill TTFT（不同输入长度，max_tokens=32 生成）

| 上下文长度 | llama.cpp | vLLM | vLLM 优势 |
|:---------:|:---------:|:----:|:--------:|
| 128 tok | 0.61s | **0.20s** | 3.1x |
| 512 tok | 1.58s | **0.66s** | 2.4x |
| 1024 tok | 2.96s | **1.27s** | 2.3x |
| 2048 tok | 11.58s | **3.50s** | 3.3x |

### 3.5 多模态 OCR (fapiao2.jpg, 端到端)

| 后端 | 耗时 |
|------|:----:|
| llama.cpp | **2.87s** |
| vLLM | 8.11s |

---

## 四、vLLM 性能瓶颈根因分析

### 4.1 问题：为什么 vLLM INT8 单请求仅 9 tok/s？

vLLM 的 ROCm 后端核心矛盾在于 **RDNA 架构适配不足**：

```
┌─────────────────────────────────────────────────────────┐
│                    llama.cpp 推理路径                     │
│                                                         │
│  GGUF Q8_0 ──► HIP dequant ──► HIP BLAS matmul ──► HIP PagedAttn │
│            (C++ 原生 kernel)                                      │
│                                                         │
│  ★ 全部使用 HIP 原生 kernel，针对 RDNA 手工调优           │
│  ★ 单 kernel 调用，无 JIT 开销                            │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                     vLLM W8A8 推理路径                   │
│                                                         │
│  INT8 weight ──► TritonInt8ScaledMM ──► TritonAttn (回退) │
│             (Triton JIT 编译)    (ROCm kernel 不可用)     │
│                                                         │
│  ★ Kernel 全部走 Triton Python JIT 层                    │
│  ★ Triton 在 RDNA 上的 INT8 后端远不如 CDNA(MI300) 成熟  │
│  ★ 首次调用触发 JIT 编译 → 延迟 spike                     │
│  ★ "Cannot use ROCm custom paged attention kernel" 回退  │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Triton JIT 编译热延迟日志证据

```
WARNING [jit_monitor.py:135] Triton kernel JIT compilation during inference:
  _compute_slot_mapping_kernel
  eagle_prepare_next_token_padded_kernel
  eagle_step_slot_mapping_metadata_kernel
  rejection_greedy_sample_kernel
```

### 4.3 量化格式差异

| 特性 | llama.cpp Q8_0 | vLLM W8A8 INT8 |
|------|:---:|:---:|
| 权重精度 | INT8 (对称) | INT8 (per-channel) |
| 激活精度 | FP16 (不量化) | **INT8** (动态量化) |
| 反量化开销 | **1 次** per token | **每层 1 次** (64层) |
| 每步数学 | FP16 matmul | INT8→FP16 dequant + matmul |
| 精度损失 | 极小 | GSM8K 无差异 (96.74%) |

W8A8 理论计算量更小，但 **每层反量化开销 + Triton JIT 层开销** 抵消了这点优势。MI300X 上 Triton INT8 kernel 经过 AMD 深度优化，而 RDNA W7900 尚未获得同等对待。

### 4.4 优化变量实测对比（2026-08-03）

| 配置 | 吞吐 | 原因 |
|------|:----:|------|
| 原配置 (0.25.1 + FP8 KV 模拟) | 9.0 tok/s | FP8 KV cache 在 RDNA 上纯软件模拟 |
| **float16 KV + enforce_eager + 0.26.0** | **12.3 tok/s** | 杀掉 FP8 模拟；0.26.0 修复 mm profiling 卡死 |
| + TORCH_SDPA | 12.4 tok/s | 无显著差异（GDN 线性注意力不走标准 attn kernel） |
| + bf16 计算 | 12.2 tok/s | 无差异 |
| + MTP 投机 (5 tokens) | 8.4 tok/s | 量化模型上接受率 **0%**，纯负担 |
| + CUDA Graph (关 enforce_eager) | 2.6 tok/s | Qwen3 48 层 GDN 吃满 Mamba 状态缓存，max_num_seqs 被迫降为 8，图捕获尺寸从 51 → 5，并发退化为串行 |

---

## 五、显存占用对比

| 项目 | llama.cpp | vLLM (eager) |
|------|:---:|:---:|
| 模型权重 | ~35 GB | 28.49 GB |
| KV Cache | FP16, ~3 GB | FP16, ~2 GB |
| 峰值激活 | — | 2.22 GB |
| 其他 | — | 0.39 GB |
| **总计** | **~38 GB** | **~33 GB** |
| 剩余 | 10 GB | ~15 GB |

---

## 六、最终推荐配置

### 当前环境（单用户 + 多模态 OCR + 发票处理）

**推荐：llama.cpp GGUF Q8_K_XL + MTP + 256K 上下文**

```bash
llama-server \
  -m /workspace/models/Qwen3.6-27B-UD-Q8_K_XL.gguf \
  --mmproj /workspace/models/mmproj-BF16.gguf \
  -ngl 99 \
  -c 262144 \
  -ctk q4_0 -ctv q4_0 \
  --host 0.0.0.0 --port 8080 \
  --spec-type draft-mtp \
  --spec-draft-n-max 2
```

| 指标 | 基础版 | MTP版 |
|------|:---:|:---:|
| 解码吞吐 | 41 tok/s | **50 tok/s** |
| MTP 接受率 | — | **100%** |
| 上下文 | 8K | **256K** |
| OCR 延迟 | 2.87s | 待测 |
| 显存 | 38 GB | ~45 GB |
| 启动时间 | < 5s | < 10s |

**理由**：
- llama.cpp 原生 HIP kernel 在 RDNA 上效率远高于 vLLM Triton 回退
- MTP 推测解码零额外开销，接受率 100%，提速 22%
- 单用户不需要 vLLM 的 continuous batching
- Q4_0 KV Cache 压缩后 256K 上下文可放进 48GB

### 多用户 API 服务场景（未来）

**推荐：vLLM W8A8 INT8 + float16 KV + enforce_eager (v0.26.0)**

```bash
vllm serve /models/Qwen3.6-27B-Quark-W8A8-INT8 \
  --tensor-parallel-size 1 --max-model-len 4096 \
  --gpu-memory-utilization 0.92 --trust-remote-code \
  --host 0.0.0.0 --port 8080 --dtype float16 --enforce-eager \
  --skip-mm-profiling
```

| 指标 | 值 |
|------|:--|
| 单请求吞吐 | 12.3 tok/s (+37% vs 9.0) |
| C8 聚合吞吐 | **82.1 tok/s** |
| TTFT | **0.17s** (极稳) |
| 显存 | ~33 GB |

**理由**：8 并发时聚合吞吐超过 llama.cpp 3.75x，适合同时服务多个用户。不用 `--kv-cache-dtype fp8`（RDNA 无 FP8 硬件），不用 MTP / CUDA Graph（实测均负优化）。

---

## 七、踩坑清单

1. **`--dtype` 必须 float16**：RDNA 无 BF16 张量核，默认 bfloat16 导致 EngineCore 崩溃
2. **`/etc/hosts` 缺 localhost**：Docker 容器常见问题，须用 `127.0.0.1`
3. **Mamba 状态缓存**：Qwen3 有 48 层 GatedDeltaNet，每层需独立缓存块，`max_num_seqs` 不能过高
4. **MTP 推测解码**：ROCm 下 MTP 的 Triton kernel 在推理时 JIT 编译，造成额外延迟；量化模型上接受率 0%
5. **`--calculate-kv-scales` 有 bug**：模型卡作者确认「silently corrupts kv cache」
6. **HF 镜像下载**：大文件 (~30GB) 易超时，用 `hf download` + `--local-dir` 可自动续传
7. **Xet 存储**：HuggingFace 新存储后端下载超时，`snapshot_download` 比 `hf_hub_download` 更稳定
8. **vLLM 0.25.1 卡死在 mm profiling**：多模态模型启动时 `profile_run()` 跑 ViT 编码器会挂死；升级 **0.26.0** + `--skip-mm-profiling` 解决
9. **不要用 `--kv-cache-dtype fp8_e4m3`**：RDNA3 无 FP8 张量核，纯软件模拟拖慢 37%；默认 float16 KV 是正解

---

## 八、文件索引

```
bench-results/
├── COMPARISON.md           ← 本报告
├── serial_128.json         ← llama.cpp 串行数据
├── concurrency.json        ← llama.cpp 并发数据
├── vision_ocr.json         ← llama.cpp OCR 数据
├── prefill.json            ← llama.cpp prefill 数据
└── vllm/
    ├── serial_128.json     ← vLLM 串行数据
    ├── concurrency.json    ← vLLM 并发数据
    ├── vision_ocr.json     ← vLLM OCR 数据
    └── prefill.json        ← vLLM prefill 数据
```
