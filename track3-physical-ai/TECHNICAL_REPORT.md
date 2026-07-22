# 1bit.systems — Real-Time NPU Inference for Robotics
## AMD AI DevMaster Hackathon 2026 · Track 3: Physical AI Challenge

---

## 1. Target Application

Real-time neural network inference for robotics perception and control loops using AMD XDNA 2 NPU and AMD Radeon GPUs. The 1bit.systems engine provides:

- **Sub-10ms inference latency** via the XDNA 2 NPU (32-tile INT8 engine)
- **Hardware-accelerated vision** for object detection, segmentation, and scene understanding
- **Deterministic latency** suitable for real-time control loops (no Python GC, no cloud dependency)
- **Multi-backend** support: NPU for low-power perception, GPU for heavy processing, CPU for fallback

## 2. System Architecture

```
Robot Sensor Input (Camera / LIDAR / Encoders)
        │
        ▼
┌─────────────────────────────────┐
│     1bit.systems Engine         │
│  ┌───────────┐  ┌───────────┐   │
│  │ Vision    │  │ Control   │   │
│  │ Pipeline  │  │ Inference │   │
│  │ (VL Model)│  │ (LLM/MoE) │   │
│  └─────┬─────┘  └─────┬─────┘   │
│        │              │         │
│  ┌─────┴──────────────┴─────┐   │
│  │   Hardware-Aware Router  │   │
│  │   NPU ↔ GPU ↔ CPU       │   │
│  └───────────┬─────────────┘   │
└──────────────┼─────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
┌────────┐         ┌────────────┐
│ XDNA 2 │         │ AMD Radeon │
│ NPU    │         │ GPU/ROCm   │
│ (32    │         │ (MI300X)   │
│ tiles) │         │            │
└────────┘         └────────────┘
```

## 3. AMD Radeon GPU Utilization

The engine utilizes AMD hardware at multiple levels:

| Component | AMD Hardware | Utilization |
|-----------|-------------|-------------|
| **INT8 inference** | XDNA 2 NPU (32 AI Engine tiles) | Matrix multiply, attention, GELU via AI Engine + DMA |
| **Vision preprocess** | Radeon GPU (HIP kernels) | Image resize, normalization (`vl_resize_norm.hip`) |
| **LLM inference** | Radeon GPU / MI300X | Flash attention, GQA, KV-cache via ROCm/HIP |
| **Mamba SSM** | Radeon GPU (custom HIP kernels) | Selective scan, A_log exponentiation |
| **Control loop** | CPU (fallback) | Deterministic path for safety-critical logic |

## 4. Key Technical Contributions

- **Full reverse-engineering of AMD's FastFlowLM NPU stack**: All 22 proprietary `.so` libraries disassembled, all 209 xclbin bitstreams traced back to AIE generators, replaced with 17.5MB open-source engine
- **32-tile INT8 GEMM on XDNA 2**: Custom instruction scheduling with dynamic activation quantization (amax-based scaling), achieving **97 tok/s**
- **Hardware-aware auto-dispatch**: Real-time routing between NPU, GPU, and CPU based on model type and hardware availability
- **Vision-language on NPU+GPU**: Qwen3-VL image preprocessing on GPU with inference on NPU

## 5. Performance Benchmarks

| Benchmark | Value | Hardware |
|-----------|-------|----------|
| NPU INT8 decode (M=32) | **97 tok/s** | XDNA 2 (32 tiles) |
| GPU ternary decode | **318 tok/s** | Vulkan ZINC |
| ROCm HIP decode | **64 tok/s** | AMD Radeon GPU |
| Prefill TFLOPS | **42.21 TFLOPS** | INT8 WMMA |
| Model load time | **<3s** (for 4B model) | Any backend |
| Binary size | **~400 KB** (exe) + **~1.1 MB** (kernel lib) | — |

## 6. Reproducibility

### Hardware Requirements
- AMD Ryzen AI Max+ 395 (Strix Halo) with XDNA 2 NPU, OR
- Any AMD Radeon GPU with ROCm support

### Software Requirements
- Ubuntu 24.04
- ROCm 7.14+ / ROCm 6.2+
- XRT (Xilinx Runtime) for NPU access
- g++ with C++23 support

### Build & Run
```bash
git clone https://github.com/bong-water-water-bong/1bit-systems
cd 1bit-systems
cmake -B build -G Ninja -DCMAKE_HIP_ARCHITECTURES=gfx1151
cmake --build build --target zaya_server -j8
./build/zaya_server --model /path/to/model.h1b
```

### Docker
A Docker image with all dependencies is available at `opea/vllm-rocm:latest`.

## 7. Team

Solo developer — bong-water-water-bong.
