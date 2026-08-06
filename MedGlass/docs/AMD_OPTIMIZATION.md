# AMD / ROCm Optimization

Every inference component runs on the AMD stack — there is no CUDA anywhere.

## Component → accelerator map (measured)

| Component | Framework | Accelerator | Quant | Measured |
|---|---|---|---|---|
| whisper-small.en | whisper.cpp (HIP build) | ROCm0 / hipBLAS | Q5_1 | RTF 0.009 (111× realtime); **6.2× vs CPU** |
| YOLOv8n-seg | ONNX Runtime | CPU EP¹ | FP16 | 88.98 ms/frame |
| Qwen3.6:27B | llama.cpp (HIP build) | ROCm0 / hipBLAS, 64/64 layers | Q4_K_M | 28 tok/s gen, 541 tok/s prompt; **5.8× vs CPU** |

¹ `ROCMExecutionProvider` is installed (`onnxruntime-rocm` 1.22.2.post3) but its
`.so` also needs `libroctracer64.so.4` (ROCm Tracer), which is not in the
Ubuntu archive, so YOLO currently runs on the ORT CPU EP. `src/config.py`
auto-detects whether the provider is actually registered and defaults
`yolo_rocm` to that reality (no more silent ORT fallback warnings); override
with `config.json` / `MEDGLASS_YOLO_ROCM`. Whisper + LLM — the two
compute-heavy stages — are fully GPU-accelerated.

## ROCm setup (as executed on this machine)

- Install system ROCm for `gfx1201`:
  `sudo apt-get install build-essential cmake clang-21 hipcc hip-utils libamdhip64-dev libhipblas-dev librocblas-dev rocm-device-libs-21 rocm-smi rocminfo`
- whisper.cpp: `cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 && cmake --build build -j`
- llama.cpp (b9180+ needed for Qwen3.6): `cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 && cmake --build build -j --target llama-cli llama-server`
- Vision EP (optional): `pip install onnxruntime-rocm` (ROCm 7.x wheel; blocked
  at runtime by missing `libroctracer64.so.4`).

## Quantization tradeoffs

| Model | Quant | Size | Why |
|---|---|---|---|
| whisper-small.en | Q5_1 | 466 MB | Good accuracy; the 5-bit integer k-quant used by ggml |
| Qwen3.6:27B | Q4_K_M | 16.8 GB | K-quant keeps quality while fitting 27B in 32 GiB VRAM |

## Memory budgeting

Models load lazily. The concurrency rule keeps the working set inside the card:

```
whisper ~1.5 GB + YOLO ~0.5 GB + LLM ~17 GB (weights) + KV cache ≈ fits 32 GiB
```

Budget lives in `src/config.py` (`memory_budget_gb`, `*_vram_gb`).

## GPU monitoring

```bash
rocm-smi --showuse --showmeminfo vram
```

`benchmarks/benchmark.py` optionally samples GPU VRAM used over time and plots
`benchmarks/gpu_utilization.png`.

## Reproducibility

`bash setup.sh` + `python benchmarks/benchmark.py` reproduces every number.
Results land in `benchmarks/cpu_vs_gpu.json`:

```json
{
  "gpu": {"name": "Navi 48 [Radeon AI PRO R9700]", "vram_gb": 31.9,
          "rocm_version": "7.1 (system ROCm)", "driver": "amdgpu (kernel)"},
  "stages": {
    "whisper": {"cpu": {"wall_ms": ...}, "gpu": {"wall_ms": ...}},
    "llm":     {"cpu": {"wall_ms": 52394}, "gpu": {"wall_ms": 9003}},
    ...
  }
}
```

Full measured table in `docs/TECHNICAL_BREAKDOWN.md`.
