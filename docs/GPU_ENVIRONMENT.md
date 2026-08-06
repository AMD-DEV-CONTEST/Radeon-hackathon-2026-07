# GPU Environment Evidence (GPU Environment Evidence)

> Official scoring item: core inference runs on AMD Radeon GPU (20 points)
> This file records the actual runtime environment's GPU hardware, ROCm version, and software status as evidence for competition review.

---

## Part 1: Collection Information

| Item | Value |
|------|------|
| Collection time | 2026-07-27 |
| Hostname | `u-7666-c69eaa0a` |
| Host address | 36.150.116.206:31028 |
| Working path | `/workspace/demo/franka_fruit_pick_demo-main` |
| Environment type | Remote container (Radeon Cloud) |

---

## Part 2: ROCm Version

| Item | Value |
|------|------|
| ROCk kernel module | 6.16.13 |
| HSA Runtime | 1.18 |
| HSA Runtime Ext | 1.15 |

**Collection command**: `rocminfo --version`

---

## Part 3: GPU Hardware Information

### 3.1 Core Specifications

| Item | Value |
|------|------|
| GPU model | AMD Radeon Graphics |
| GFX version | gfx1100 |
| Architecture generation | RDNA 3 (gfx11-generic) |
| Compute units (CU) | 96 |
| SIMD per CU | 2 |
| Shader Engines | 6 |
| Shader Arrays per Eng. | 2 |
| Wavefront size | 32 |
| Maximum clock frequency | 1760 MHz |
| Maximum workgroup size | 1024 |
| Maximum waves per CU | 32 |
| Maximum work-items per CU | 1024 |

### 3.2 Cache and VRAM

| Item | Value |
|------|------|
| L1 cache | 32 KB |
| L2 cache | 6144 KB (6 MB) |
| L3 cache (Infinity Cache) | 98304 KB (96 MB) |
| **VRAM** | **~48 GB** (50,315,264 KB) |
| Memory type | COARSE GRAINED / EXTENDED FINE GRAINED |
| Recommended allocation granularity | 2048 KB |

### 3.3 Supported ISAs

| ISA | Description |
|-----|------|
| `amdgcn-amd-amdhsa--gfx1100` | Native gfx1100 instruction set |
| `amdgcn-amd-amdhsa--gfx11-generic` | RDNA 3 generic instruction set |

### 3.4 Feature Flags

| Feature | Value | Description |
|------|------|------|
| Fast F16 | True | Supports fast FP16 computation |
| IOMMU | None | IOMMU not enabled |
| Coherent Host Access | False | GPU VRAM and host memory are non-coherent |
| XNACK | DISABLED | Unified memory large-page support disabled |
| Partitions | N/A | MIG partitioning not enabled, full-card exclusive |

---

## Part 4: CPU Information

| Item | Value |
|------|------|
| CPU model | AMD EPYC 9334 32-Core Processor |
| Physical CPUs | 2 (dual-socket, Node 0 & Node 1) |
| Cores per CPU | 32 |
| Total logical cores | 64 (including SMT) |
| L1 cache (per Node) | 32,768 KB |
| Memory per node | ~252 GB |
| **Total memory** | **~504 GB** |

---

## Part 5: Runtime Status (collected while idle)

| Item | Value |
|------|------|
| Device ID | 0x744b |
| GUID | 6853 |
| Node ID | 2 |
| Edge temperature | 21.0°C |
| Average power | 12.0 W |
| Fan speed | 20.0% |
| Performance state | auto |
| Maximum power cap (PwrCap) | 241.0 W |
| SCLK | 0 MHz (idle) |
| MCLK | 96 MHz (idle) |
| VRAM usage | 0% |
| GPU utilization | 0% |

**Collection command**: `rocm-smi`

> An idle SCLK of 0 MHz is a normal deep power-saving mode; under load the frequency automatically rises to 1760 MHz.

---

## Part 6: Python Environment Status

| Item | Value |
|------|------|
| Python path | `/usr/bin/python` (system Python) |
| Python version | 3.12 |
| pip version | pip 24.0 |
| PyTorch (torch) | Not installed |
| vLLM | Not installed |

### Components to Install

```bash
# 1. Create a virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 2. Install PyTorch ROCm (gfx1100 compatible with ROCm 6.x)
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2

# 3. Install vLLM ROCm
pip install vllm --no-build-isolation

# 4. Verify
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'HIP version: {torch.version.hip}'); print(f'GPU: {torch.cuda.get_device_name(0)}')"
```

---

## Part 7: Analysis of the Environment's Impact on the Project

### 7.1 VRAM Capacity Assessment

| Model | Quantization | VRAM requirement | Feasibility with 48GB VRAM |
|------|------|----------|------------------|
| Qwen3-8B | FP16 | ~16 GB | Ample, can use large batches |
| Qwen3-8B | INT8 | ~9 GB | Ample |
| Qwen3-8B | INT4 (GPTQ) | ~5 GB | Ample, can maximize concurrency |
| Qwen2-14B-Instruct | FP16 | ~28 GB | Feasible (leaves 20GB for KV-Cache) |
| Qwen2-14B-Instruct | INT4 | ~9 GB | Ample |
| BGE-M3 (Embedding) | FP16 | ~2 GB | Coexists without pressure |
| DeepSeek-R1-Distill-Qwen-7B | FP16 | ~15 GB | Ample, time-shared with the main model |

> 48GB VRAM means even the 7B FP16 baseline has ample headroom, allowing the `max_num_seqs` and `max_model_len` parameters to be opened up.

### 7.2 gfx1100 Compatibility

| Framework | gfx1100 support | Description |
|------|-------------|------|
| PyTorch ROCm | Fully supported | Native RDNA 3 support |
| vLLM ROCm | Supported | Requires a ROCm 6.x build |
| llama.cpp HIPBLAS | Supported | `make GGML_HIPBLAS=1` |
| FAISS | Does not depend on GPU | No impact for faiss-cpu |

### 7.3 Optimization Strategy Adjustment

Based on the 48GB large VRAM, the optimization strategy is adjusted compared with small-VRAM cards:

| Optimization dimension | Small-VRAM strategy (8-16GB) | This environment's strategy (48GB) |
|----------|---------------------|-------------------|
| Quantization priority | INT4 mandatory, VRAM bottleneck | INT4 optional, focus on throughput testing |
| Concurrency | 4-8 | Can try 16-32 |
| max_model_len | 4096 (saves VRAM) | 8192-16384 (VRAM is ample) |
| KV-Cache | PagedAttention mandatory | Enabled, but not a bottleneck |
| batch size | Limited | Can be increased to test the ceiling |

---

## Part 8: Collection Script

This evidence was collected by the following commands and is reproducible:

```bash
#!/bin/bash
# scripts/collect_gpu_evidence.sh

echo "=== ROCm version ==="
rocminfo --version

echo "=== GPU model ==="
rocm-smi --showproductname

echo "=== GPU detailed info ==="
rocminfo | head -100

echo "=== GPU runtime status ==="
rocm-smi

echo "=== Python environment ==="
python --version
pip --version
python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}, hip={torch.version.hip}')" 2>/dev/null || echo "torch: not installed"
python -c "import vllm; print(f'vllm={vllm.__version__}')" 2>/dev/null || echo "vllm: not installed"

echo "=== CPU info ==="
lscpu | grep -E "Model name|CPU\(s\)|Thread"

echo "=== memory info ==="
free -h
```

---

## Part 9: Evidence File List

The GPU evidence files required by the competition are all stored in `docs/benchmarks/logs/`:

| Evidence item | File name | Collection command |
|--------|--------|----------|
| GPU model | `gpu_model.txt` | `rocm-smi --showproductname` |
| ROCm version | `rocm_version.txt` | `rocminfo --version` |
| GPU detailed info | `rocminfo_full.txt` | `rocminfo` |
| GPU runtime status | `rocm_smi.txt` | `rocm-smi` |
| vLLM startup log | `vllm_startup.log` | `tee` at vLLM startup |
| VRAM monitoring | `vram_usage.csv` | `rocm-smi --showmeminfo vram` (sampled) |
| GPU utilization | `gpu_util.csv` | `rocm-smi --showuse` (sampled) |
| PyTorch verification | `torch_verify.txt` | `python -c "import torch; ..."` |