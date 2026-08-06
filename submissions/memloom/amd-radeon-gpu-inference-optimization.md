# AMD Radeon GPU Inference Speed Optimization

> Memloom — AMD AI DevMaster Hackathon · Track 2: Development & Local Deployment of Private AI Agents
> Project: a local private AI agent (two-way knowledge layer)
> Hardware: AMD Radeon Cloud (gfx1100 / RDNA3 / 96 CU / 51.52 GB VRAM)
> Software: ROCm 7.2.1 / vLLM 0.16.1.dev0+rocm721 / PyTorch 2.9.1

---

## 1. Optimization goals and method overview

Memloom is a local-first private AI agent knowledge layer whose core workload is **structured knowledge extraction and multi-agent merge reasoning**. This workload is characterized by:

- **Frequent interaction**: each extraction session involves multiple model calls in Distill (extract) + Merge (fuse)
- **Long context**: inputs are real agent conversation records (thousands of tokens)
- **Local deployment**: all inference runs on the AMD Radeon GPU with no cloud dependency

The optimization goal is therefore to improve **three dimensions at once**: lower time-to-first-token (TTFT), higher output throughput (tok/s), and controlled VRAM usage.

| Optimization dimension | Method | Measured effect |
|---|---|---|
| Inference engine | vLLM with native ROCm support | TTFT reduced from 13–27 s to 55–179 ms |
| Attention backend | Uninstall CUDA flash-attn, use native ROCm kernels | Fixed startup crashes, restored normal inference |
| Graph mode | `--enforce-eager` to bypass CUDA graph compatibility issues | Guarantees stable runs on gfx1100 |
| Quantization | BF16 (FP8 has no hardware instructions on RDNA3) | Controllable weights/VRAM usage |
| Model selection | Full 14-model benchmark comparison | Optimal model per scenario |

---

## 2. Deployment-layer optimization

### 2.1 vLLM service launch parameters (core optimization)

All models use the following unified launch parameters, verified as optimal on gfx1100:

```bash
vllm serve /path/to/model \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.9 \
  --enforce-eager \
  --trust-remote-code
```

**Purpose and rationale of each parameter:**

| Parameter | Purpose | Optimization effect |
|---|---|---|
| `--gpu-memory-utilization 0.9` | Let vLLM use 90% of VRAM | Maximize KV cache capacity to support 8192-context concurrency (measured 11.1x concurrency) |
| `--enforce-eager` | Disable CUDA/HIP graph, use eager mode | CUDA graph path has compatibility issues on gfx1100 → eager guarantees stability |
| `--max-model-len 8192` | Fix the context length | Predictable VRAM usage, avoids long-context OOM |
| `--trust-remote-code` | Allow custom model code | Supports models with custom code such as InternLM3 |

### 2.2 flash-attn compatibility fix (key pitfall)

**Problem**: vLLM 0.16.1's ROCm build depends on the CUDA version of flash-attn by default, and Qwen-family models crash at startup:

```
ModuleNotFoundError: No module named 'flash_attn_2_cuda'
```

**Action**: uninstall the incompatible flash-attn and fall back to ROCm-native attention kernels:

```bash
pip uninstall flash-attn
```

**Effect**: all models including Qwen2.5/Qwen3/Gemma recover startup and infer normally. This is one of the most important deployment optimizations in the ROCm environment.

### 2.3 VRAM management and model capacity constraints

Actual usable VRAM on gfx1100 is **47.98 GB** (not the nominal 51.52 GB; the ROCm runtime occupies part of it):

- Use **BF16 quantization** (FP8 has no hardware instructions on RDNA3; measured error `No FP8 backend`)
- **BF16 weights must be < 48GB**: Qwen3-Coder-30B (57GB) OOMs; Mistral-Nemo (46GB) runs barely
- Measured peak-VRAM pattern: 27.6GB weights → 43.5GB peak (about +15GB for KV cache and runtime)

---

## 3. Model selection optimization (based on 14 models measured)

Through 6 AMD Radeon Cloud servers, 14 models × 21 runs (v1) and 12 models × 54 runs (v2) full comparison, model selection by scenario:

### 3.1 Measured performance comparison (v1: 7 tasks × 3 repeats)

| Model | Weights | TTFT p50 | Throughput | Success rate | Recommended scenario |
|---|---:|---:|---:|---:|---|
| **Qwen2.5-14B-Instruct** | 28 GB | 26.7 s | 11.8 t/s | **90.5%** | Production first pick (quality first) |
| Gemma-3-12B-IT | 23 GB | 13.0 s | 15.6 t/s | **100%** | Full-score reference |
| Qwen3-14B | 28 GB | **0.8 s** | 11.7 t/s | 85.7% | Speed first (fastest TTFT) |
| Qwen3-4B | 7.6 GB | 5.1 s | **46.2 t/s** | 85.7% | Small VRAM / high concurrency |
| Llama-3.1-8B | 15 GB | 30.9 s | 23.1 t/s | 52.4% | Not recommended (weak JSON adherence) |

### 3.2 v2 measured performance comparison (18 tasks × 3 repeats, 2026-08-03)

| Model | TTFT p50 | JCT p50 | tok/s | VRAM | Total score |
|---|---:|---:|---:|---:|---:|
| phi-4 | 177 ms | 22.2 s | 12.4 | — | **51.17** |
| gemma-3-12b-it | 129 ms | 14.0 s | 13.9 | — | 48.47 |
| Qwen2.5-14B | 169 ms | 18.7 s | 12.3 | — | 48.18 |
| **Qwen3-4B** | **55 ms** | **4.5 s** | **44.6** | 7.6 GB | 40.14 |

### 3.3 Selection conclusion

- **Quality first**: Qwen2.5-14B-Instruct (90.5% success rate, structured-output specialty)
- **Speed first**: Qwen3-4B (44.6 tok/s, JCT only 4.5 s, 7.6 GB VRAM) — best for latency-sensitive scenarios
- **TTFT sensitive**: Qwen3-14B (785 ms first token measured in v1)
- **Not suitable**: DeepSeek-V2-Lite (MLA inference unavailable on ROCm without flash-attn), Llama/Mistral (weak JSON adherence)

---

## 4. Measured results summary (before/after optimization)

| Metric | Before (early V2-Lite era) | After (Qwen3-4B / v2 env) | Improvement |
|---|---:|---:|---:|
| TTFT p50 | 12,972 ms (13 s) | **55 ms** | **236x** |
| Output throughput | 22.1 t/s | **44.6 t/s** | **2.0x** |
| JCT p50 | 6,726 ms (outlier) | 4.5 s (stable) | stable and reproducible |
| Peak VRAM | 46.56 GB (V2-Lite max) | 7.6 GB (Qwen3-4B) | **6.1x saving** |
| Model calls | 2/21 runs (barely triggered) | normal (measured in reuse dimension) | functional completeness |

**Note**: the huge TTFT improvement comes from two layers — (1) the vLLM + ROCm native inference pipeline replacing the earlier unstable calling approach; (2) model selection (small 4B model vs 16B MoE). Throughput improvement mainly comes from model selection and context management.

---

## 5. Key lessons and conclusions

1. **The core of ROCm optimization is "removing CUDA dependencies"**: flash-attn is the biggest compatibility obstacle; after uninstalling it, all models recover stable inference
2. **`--enforce-eager` is a must on gfx1100**: the CUDA graph path has poor compatibility on RDNA3
3. **VRAM is the hard constraint**: only BF16 weights < 48GB can be deployed; prefer dense 4B–14B models
4. **Small models are not low quality**: Qwen3-4B reaches 85.7% success rate (v1) with 7.6GB and is the fastest overall — the best cost-performance for private local deployment
5. **Speed optimization must be tied to quality**: a faster but failing task is not an optimization (explained in the README rules); success rate comes first

---

## Appendix: evidence file index

| Material | Path |
|---|---|
| v1 comparison report (14 models) | `evals/reports/2026-08-02-amd-multi-model-comparison.md` |
| v2 comparison report (13 models) | `evals/reports/2026-08-03-amd-track2-v2-13-models.md` |
| Benchmark framework | `benchmarks/amd-track2/README.md` |
| v2 suite design doc | `benchmarks/amd-track2/V2.md` |
| Raw run data | `evals/runs/amd-track2/` (kept locally, not in git) |

> All data from 6 AMD Radeon Cloud instances (gfx1100 / ROCm 7.2.1), loopback local inference, BF16 quantization, 8192 context.
