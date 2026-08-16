# Model Tuning Guide

> Silent Core Model Service — LLM inference optimization on AMD Radeon GPU

## Overview

The tuning process follows three steps: (1) check GPU status, (2) run
baseline benchmark, (3) compare different parameters.

This guide documents the actual tuning process performed on an AMD Radeon
`gfx1100` GPU with 48 GB VRAM (ROCm 7.2.1).

## Step 1: Check GPU status

```bash
rocm-smi --showuse --showmeminfo vram --showpower --showtemp
```

Key metrics to watch:

| Metric | Idle | During Inference | Concern Level |
|--------|------|------------------|---------------|
| GPU Use | 0% | 80-100% | < 50% under load = bottleneck |
| VRAM Used | ~26 MB | ~5.75 GB (LLM only) | Near 48 GB = OOM risk |
| Temperature | 25°C | < 70°C | > 85°C = throttle risk |
| Power | 15W | 200-300W | — |

## Step 2: Run baseline benchmark

```bash
/workspace/llama.cpp/build/bin/llama-bench \
  -m /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  -ngl 99 -t 16 -fa 1 -p 512 -n 128
```

Parameters explained:

| Flag | Value | Meaning |
|------|-------|---------|
| `-m` | model path | Qwen3-8B Q4_K_M quantized model |
| `-ngl` | 99 | GPU layers to offload (99 = all layers) |
| `-t` | 16 | CPU threads for prompt processing |
| `-fa` | 1 | Flash Attention enabled |
| `-p` | 512 | Prompt size (tokens) for prefill test |
| `-n` | 128 | Generation length for decode test |

Output metrics:
- `pp512` = prompt processing speed (tokens/s, higher is better)
- `tg128` = token generation speed (tokens/s, higher is better)

## Step 3: Compare parameters

Run each test and record the results:

```bash
# Test A: Flash Attention OFF
/workspace/llama.cpp/build/bin/llama-bench \
  -m /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  -ngl 99 -t 16 -fa 0 -p 512 -n 128

# Test B: 8 threads (vs 16)
/workspace/llama.cpp/build/bin/llama-bench \
  -m /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  -ngl 99 -t 8 -fa 1 -p 512 -n 128

# Test C: Reduced GPU layers (15 instead of 99)
/workspace/llama.cpp/build/bin/llama-bench \
  -m /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  -ngl 15 -t 16 -fa 1 -p 512 -n 128
```

### Benchmark Results (gfx1100, 48 GB VRAM, ROCm 7.2.1)

| Config | GPU Layers | Threads | Flash Attn | pp512 (t/s) | tg128 (t/s) | Notes |
|---|---:|---:|---|---:|---:|---|
| **Baseline (best)** | 99 | 16 | on | 2989 | **93.32** | Current production config |
| Flash Attn off | 99 | 16 | off | 2774 | 87.65 | 6% slower |
| 8 threads | 99 | 8 | on | 2984 | 92.77 | Minimal difference |
| Reduced GPU layers | 15 | 16 | on | 395 | 10.03 | **89% slower** — avoid |

### Conclusions

1. **Flash Attention**: ~6% speedup — always enable (`--flash-attn on`)
2. **Thread count**: 8 vs 16 threads shows negligible difference on this GPU
3. **GPU layers**: Reducing from 99 to 15 causes catastrophic 89% slowdown — keep all layers on GPU
4. **Quantization**: Q4_K_M provides 3.8x throughput vs BF16 baseline while using 1/3 VRAM

## Step 4: API-level tuning (temperature)

The `temperature` parameter controls output randomness:

```bash
# Low temperature (0.3) = stable, precise, deterministic output
curl -s -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/chat/completions \
  -d '{"model":"silent-core/llm","messages":[{"role":"user","content":"Write a fantasy scene"}],"max_tokens":256,"temperature":0.3}'

# High temperature (1.0) = more creative, varied, unpredictable
curl -s -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/chat/completions \
  -d '{"model":"silent-core/llm","messages":[{"role":"user","content":"Write a fantasy scene"}],"max_tokens":256,"temperature":1.0}'
```

| Temperature | Effect | Use Case |
|-------------|--------|----------|
| 0.1-0.3 | Deterministic, focused | Code generation, factual Q&A |
| 0.4-0.6 | Balanced | General chat, summaries |
| 0.7-0.9 | Creative, varied | **Narrative generation (recommended)** |
| 1.0+ | Highly random | Brainstorming, experimental |

## Monitoring During Tuning

Watch GPU usage in real-time while running benchmarks:

```bash
# Real-time GPU monitor (refresh every 1 second)
watch -n 1 rocm-smi --showuse --showmeminfo vram --showpower --showtemp
```

What to expect:
- **pp512 test**: GPU usage spikes to 80-100% briefly (parallel processing)
- **tg128 test**: GPU usage stays at 60-90% sustained (sequential generation)
- **Idle between tests**: GPU drops back to 0%, VRAM stays allocated (~5.75 GB)

## Production Configuration

The final production configuration used for the hackathon submission:

```bash
# LLM (optimal config from benchmark)
/workspace/llama.cpp/build/bin/llama-server \
  --model /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8081 \
  --n-gpu-layers 99 --ctx-size 8192 --threads 16 \
  --batch-size 512 --flash-attn on

# Image (CPU offload to avoid VRAM contention with LLM)
export IMAGE_MODEL_PATH="/data/models/Z-Image-Turbo"
export IMAGE_CPU_OFFLOAD="true"

# TTS (CPU only, no GPU usage)
# Runs on 16 CPU threads, does not compete with GPU workloads

# Gateway
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
```
