> **📜 Hackathon submission** — This document was created for the AMD Radeon Hackathon 2026-07 and reflects the project state at that time (July 2026). Numbers like "97 tok/s" NPU and FastFlowLM references are historical — see the [README](../README.md) and [current benchmarks](../docs/wiki/performance.md) for up-to-date data.
>
# AMD AI DevMaster Hackathon — Track 2 Submission
## Development & Local Deployment of Private AI Agents

**Team**: 1bit.systems  
**Project**: 1bit.systems — One Binary, All Backends, Zero Cloud  
**Date**: July 2026  
**Hardware**: AMD Ryzen AI Max+ 395 (Strix Halo) — Radeon 8060S GPU + 32 XDNA 2 NPU tiles + 128 GB unified LPDDR5X

> **On hardware**: this submission runs entirely on the team's own local AMD Strix Halo
> machine — a real Radeon 8060S GPU and XDNA 2 NPU, not AMD's Radeon Cloud offering.
> We chose local hardware because it's the more demanding and more honest proof of the
> track's own core requirement ("core inference must run locally, no reliance on
> closed-source APIs") — the NPU driver itself was reverse-engineered from scratch
> against this physical silicon (see §7 and `docs/journey.md`), which wouldn't have been
> possible against a generic cloud GPU instance.

---

## 1. Application Scenarios

1bit.systems enables **fully private, on-device AI agents** on consumer AMD hardware. No cloud, no API keys, no data leaving the machine. Target scenarios:

| Scenario | Description |
|----------|-------------|
| **Personal AI Assistant (Jarvis)** | Local voice agent with multi-turn memory, tool invocation, and multi-step planning. Runs entirely on Strix Halo. Handles scheduling, code generation, research summarization, and device control — all on-device. |
| **Code Review & Audit Agent** | Offline code analysis agent that audits private repositories without uploading code to cloud services. Integrates with Git, runs linters, and generates patch suggestions locally. |
| **Privacy-Critical Document Analysis** | Local RAG pipeline over financial, legal, or medical documents. Embedding + generation run on NPU, vector store on local SSD. Zero data exfiltration. |
| **Edge Video Analytics** | Real-time video understanding (VL model) on local camera feeds. All inference on GPU/NPU. Used for security monitoring, retail analytics, or industrial inspection without cloud dependency. |
| **LAN Voice Demo (1bit Mobile)** | Phone-to-device voice pipeline: record → transcribe → generate → synthesize → play through physical speaker. LAN auto-discovery via UDP beacon. No internet required. |

---

## 2. Agent Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Client (1bit Mobile / CLI)               │
│  Voice Input → Whisper STT → POST /v1/chat/completions      │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP (OpenAI-compatible API)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   unified_server (C++, ~2 MB)                │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Model Router │  │ Token Router │  │ Strategy Engine   │  │
│  │ (auto-detect │  │ (per-request │  │ (cascade,         │  │
│  │  architecture│  │  dispatch)   │  │  spec_decode,     │  │
│  │  from header)│  │              │  │  parallel_moe)    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                 │                    │             │
│         ▼                 ▼                    ▼             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Backend Manager (auto-failover)          │   │
│  │                                                       │   │
│  │  Tier 1: ROCm HIP     Tier 3: Vulkan    Tier 5: CPU   │   │
│  │  │ Q1 GEMV 433 t/s   │ GPU ternary    │ OpenMP      │   │
│  │  │ Fused TQ2 420 t/s │ ZINC 22 t/s    │ fallback    │   │
│  │  │ Mamba1 79.8 t/s   │                │             │   │
│  │  └────────────────────┴────────────────┴─────────────┘   │
│  │  Tier 2: XDNA 2 NPU   Tier 4: Vulkan ZINC               │
│  │  │ NPU v12 69 t/s    │                               │   │
│  │  │ FLM bridge        │                               │   │
│  └──────────────────────┴───────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Jarvis Agent Layer                                   │   │
│  │  │ Memory (multi-turn context)                       │   │
│  │  │ Tools (code exec, web fetch, file I/O)            │   │
│  │  │ Planning (multi-step decomposition)               │   │
│  │  │ Permission Gate (user approval for risky ops)     │   │
│  │  │ Audio Out (USB speaker mirror via aplay)          │   │
│  │  │ LAN Beacon (UDP broadcast for auto-discovery)     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Agent Watchdog (self-healing)                        │   │
│  │  │ Monitors backend health, detect hangs/crashes     │   │
│  │  │ Auto-restart failed backends                      │   │
│  │  │ Cascade to fallback on error                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              AMD Strix Halo Hardware                         │
│                                                              │
│  ┌─────────────────────┐    ┌────────────────────────────┐  │
│  │ Radeon 8060S GPU    │    │ XDNA 2 NPU (32 tiles)      │  │
│  │ gfx1151, ROCm HIP   │    │ INT8 GEMM @ 50 TOPS        │  │
│  │ Vulkan 1.3          │    │ Q4NX tiled DMA             │  │
│  └────────┬────────────┘    └─────────────┬──────────────┘  │
│           │                                │                 │
│           └──────────┬─────────────────────┘                 │
│                      ▼                                       │
│         128 GB unified LPDDR5X memory                        │
│         (zero-copy between GPU ↔ NPU ↔ CPU)                  │
└─────────────────────────────────────────────────────────────┘
```

**Key architectural decisions:**

1. **Single binary, zero dependencies** — no Python, no Rust runtime, no Docker. Just `g++ -std=c++23` and run.
2. **Auto-detection from model header** — models are discovered from `.h1b`/`.1bp`/GGUF headers. No config.json, no model registry.
3. **Token-level routing** — each token can be dispatched to a different backend. Fast attention tokens go to GPU, heavy FFN tokens go to NPU.
4. **Self-healing watchdog** — monitors backend health, detects hang/crash, auto-restarts or cascades to fallback.
5. **Unified memory** — Strix Halo's 128 GB LPDDR5X is shared between GPU, NPU, and CPU. Zero-copy weight sharing between backends.

---

## 3. Core Capabilities

### 3.1 Multi-Backend Inference Engine
- **10+ model architectures**: Qwen3 (0.6B–35B MoE), BlackMamba 1.5B/2.8B (SSM hybrid), Zamba2 7B, Llama 3.1 8B, DeepSeek R1 Distill 7B, Phi-4 mini, Gemma4 E2B, Bonsai 4B TQ2
- **4 quantization formats**: Q4NX (NPU INT8), TQ2 (GPU ternary 1.58-bit), GGUF Q4_K/Q8_0, FP16/FP32
- **6 routing strategies**: Auto, Cascade, Speculative Decode (MTP), Parallel MoE, Content-aware, Passthrough

### 3.2 Jarvis Agent
- **Multi-turn memory** — conversation context preserved across turns
- **Tool invocation** — code execution, web fetch, file I/O, shell commands (permission-gated)
- **Multi-step planning** — decomposes complex tasks into sub-steps with dependency tracking
- **Voice pipeline** — Whisper transcription → agent reasoning → TTS synthesis → USB speaker playback
- **LAN auto-discovery** — UDP beacon on port 13305 for 1bit Mobile auto-connection

### 3.3 OpenAI-Compatible API
- `POST /v1/chat/completions` — chat with any loaded model
- `POST /v1/completions` — legacy completion
- `GET /v1/models` — list available models
- `GET /v1/health` — backend status dashboard
- `POST /v1/audio/transcriptions` — speech-to-text
- `POST /v1/audio/speech` — text-to-speech
- A2A Protocol (`/a2a/v1/message:send`) — agent-to-agent interoperability

---

## 4. Model Introduction & Local Deployment

### 4.1 Supported Models

| Model | Size | Architecture | Best Backend | Performance |
|-------|------|-------------|-------------|-------------|
| Qwen3-0.6B | 0.6B | Dense Transformer | NPU v12 | 69 tok/s |
| Qwen3-4B | 4B | Dense Transformer | GPU ternary | 318 tok/s |
| Qwen3-27B Q4_K | 27B | Dense Transformer | ROCm HIP | 30 tok/s |
| Qwen3-35B MoE Q4_K | 35B | MoE Transformer | ROCm HIP | 20 tok/s |
| BlackMamba-1.5B | 1.5B | Mamba1 SSM + MoE | Mamba1 HIP | 79.8 tok/s |
| BlackMamba-2.8B | 2.8B | Mamba1 SSM + MoE | Mamba1 HIP | 46.4 tok/s |
| Zamba2-7B | 7B | Mamba2 Hybrid | GPU ternary | ~30 tok/s |
| Llama-3.1-8B | 8B | Dense Transformer | GPU ternary | ~25 tok/s |
| DeepSeek R1 Distill 7B | 7B | MoE Transformer | ROCm HIP | ~25 tok/s |
| Phi-4-mini | 3.8B | Dense Transformer | GPU ternary | ~35 tok/s |

### 4.2 Model Formats
- **1BP** (native) — 256-byte header, memory-mappable weights, zero config. The project's own single-file format.
- **GGUF** — full support with K-quant, mmap, and architecture auto-detection. Read directly via `gguf_reader.cpp`.
- **Q4NX** — AMD's own NPU tiled layout, fully reverse-engineered. Read natively via `npu_engine_universal.cpp`.
- Converters available: `zamba7b_to_gguf.py`, `gguf_to_1bp.cpp`, `safetensors_to_q4nx.py`

### 4.3 Deployment

```bash
# One command to run everything
./build/unified_server --model blackmamba-1.5b.1bp --port 8088

# Or zero-arg auto-discovery
./build/unified_server
# → Auto-detects all .1bp/.gguf/.h1b files in weights dir
# → Auto-detects available hardware (HIP > NPU > Vulkan > CPU)
# → Starts HTTP server on port 8088
```

**Zero configuration files.** The server auto-detects:
- Model architecture from binary header (no config.json)
- Available hardware (HIP device count, XRT NPU presence, Vulkan devices)
- Best backend per model (profiles at startup, caches results)

---

## 5. Inference Optimization for AMD Radeon GPU

### 5.1 GPU Kernel Optimization (ROCm HIP)

| Technique | Impact | Details |
|-----------|--------|---------|
| **1-bit ternary packing (TQ2)** | 8× memory reduction vs FP16 | Pack weights as 2-bit codes. Dequantize in-register during GEMV. 2560 bytes/tile vs 5120 for INT8 Q4NX. |
| **Q1 GEMV fused kernel** | 433 tok/s (synthetic) | Single HIP kernel that reads packed Q1_0 weights, dequantizes in registers, and accumulates dot products. Avoids separate dequant+matmul passes. |
| **Fused QKV+Gate+Up** | 420 tok/s (synthetic) | Gate and Up projections computed in the same kernel launch as QKV attention. Reduces kernel launch overhead by 4× for transformer layers. |
| **Structure-of-Arrays layout** | 2.3× throughput | Weights stored as SoA (not AoS) for coalesced memory access. 4-row batching for small-M GEMV. |
| **Mamba1 SSM HIP kernel** | 79.8 tok/s (BlackMamba) | Custom HIP kernel for selective state-space model. Fused A_log exponentiation, conv state management, and selective scan in one launch. |
| **Mamba2 HIP kernels** | MI300X + Radeon | Selective scan + conv1d HIP kernels with PyTorch ctypes extension. Enables fast Mamba2 training on AMD GPUs. |
| **Speculative decoding (MTP)** | ~50% speedup | Multi-token prediction with draft model + target model verification. Run draft on NPU (cheap), verify on GPU (accurate). |
| **INT8 WMMA prefill** | 39.4 TFLOPS | Uses AMD WMMA intrinsics for matrix multiply-accumulate in INT8. Full prompt prefill in a single kernel launch. |

### 5.2 NPU Optimization (XDNA 2)

| Technique | Impact | Details |
|-----------|--------|---------|
| **Q4NX native dispatch** | 69 tok/s | Direct XRT BO allocation and DMA to NPU tiles. No FastFlowLM subprocess. Zero-copy between CPU and NPU via shared BOs. |
| **Column unlock** | 40 AIE columns | Reverse-engineered AMD's column-count lock. Patched `amdxdna.ko` kernel module to access all 40 AIE columns (vendor-locked to 20). |
| **Pipeline overlap** | 1.4× throughput | DMA upload + NPU compute + DMA download pipelined across tiles. Next tile loads while current tile computes. |
| **FastFlowLM removed** | Zero proprietary code | All 22 proprietary `.so` fully reverse-engineered and replaced. FastFlowLM removed entirely (PR #589, #632). Zero closed-source dependencies. |

### 5.3 System-Level Optimization

| Technique | Impact | Details |
|-----------|--------|---------|
| **Unified memory (zero-copy)** | Eliminates PCIe transfers | Strix Halo's shared LPDDR5X means GPU, NPU, and CPU all see the same physical memory. Model weights loaded once, used by all backends. |
| **Cross-backend cascade** | Best-of-all-worlds latency | Each token profiled across backends at startup. Router dispatches to fastest available. Fallback on error. |
| **Memory-mapped model loading** | Instant startup | GGUF and 1BP formats support mmap. Model weights mapped into process address space, paged in on-demand by OS. |
| **Single-binary C++23 server** | Minimal attack surface | Statically-linked, no Python interpreter, no pip packages, no Docker layers. |

### 5.4 Comparative Performance

| Engine | Hardware | tok/s (Qwen3-0.6B) | Status |
|--------|----------|-------------------:|--------|
| **1bit-systems GPU 1-bit** | Radeon 8060S (ROCm HIP) | **417** | Fused Q1 GEMV kernel |
| **1bit-systems GPU ternary** | Radeon 8060S (Vulkan) | **318** | TQ2 1.58-bit packing |
| **1bit-systems NPU v12** | XDNA 2 (32 tiles) | **97** | Native Q4NX + pipeline overlap |
| llama.cpp ROCm (PrismML) | Same hardware | 229 | Reference baseline |
| FastFlowLM | — | — | Removed — zero proprietary code |

---

## 6. Project Source Code

- **Repository**: https://github.com/bong-water-water-bong/1bit-systems
- **License**: MIT
- **Language**: C++23 (server), HIP C++ (GPU kernels), Python (converters/benchmarks), Rust (proxy)
- **Build**: CMake + Ninja, `cmake -B build -G Ninja && ninja -C build zaya_server`
- **Binary size**: ~1.4 MB server (`zaya_server`) + ~1.7 MB HIP kernel library (`librocm_cpp.so`)

### Repository Structure
```
1bit-systems/
├── tests/zaya_server.cpp      ← HTTP server (OpenAI API)
├── tools/unified_server.cpp   ← Unified server with auto-discovery
├── src/                       ← HIP GPU kernels (ternary, Q1, Mamba1)
├── engine/npu/                 ← NPU engine (XDNA 2, Q4NX, xclbin)
├── backends/                   ← Backend abstraction layer
├── tools/jarvis_server.cpp     ← Agent layer, native C++ (RAG, tools, planning, memory)
├── packaging/services/          ← Systemd service unit
├── rust/                       ← Rust reverse proxy (onebit)
├── scripts/                    ← Converters, benchmarks, CI
├── hackathon/                  ← Submission materials
├── models/                     ← 40 models across 16 families on HuggingFace
└── site/                       ← https://1bit.systems
```

---

## 7. Innovation Summary

1. **Reverse-engineered AMD NPU in 4 days** — 22 proprietary `.so` libraries, 209 xclbin bitstreams, full stack rebuilt open-source
2. **1BP format** — single-file model format with 256-byte header, eliminates config-file sprawl across GGUF/ONNX/safetensors
3. **1.58-bit ternary quantization** — TQ2 packing achieves near-FP16 quality at 8× smaller size, runs on Vulkan (portable) and HIP (fast)
4. **Token-level multi-backend routing** — each token dispatched to the fastest available backend, with auto-failover
5. **Self-healing agent watchdog** — monitors hardware health, detects hangs, restarts backends without human intervention
6. **Zero-Python inference** — entire inference pipeline in C++23, from model loading through token sampling to HTTP response
7. **Unified memory exploitation** — leverages Strix Halo's shared 128 GB LPDDR5X for zero-copy GPU↔NPU↔CPU weight sharing

---

## 8. Team

**bong-water-water-bong** — Solo developer  
1800+ hours of engineering on Strix Halo.  
Reverse-engineered AMD's XDNA 2 NPU with no documentation.  
Built the full stack: NPU driver patches → kernel compiler → GPU kernels → inference server → agent layer → mobile client.

---

*Generated for AMD AI DevMaster Hackathon — Track 2 Submission*
