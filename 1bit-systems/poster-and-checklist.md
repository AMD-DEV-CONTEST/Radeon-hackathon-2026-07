> **📜 Hackathon submission** — This document was created for the AMD Radeon Hackathon 2026-07 and reflects the project state at that time (July 2026). Numbers like "97 tok/s" NPU and FastFlowLM references are historical — see the [README](../README.md) and [current benchmarks](../docs/wiki/performance.md) for up-to-date data.
>
# AMD AI DevMaster Hackathon — Track 2
## Submission Checklist

Team: **1bit.systems**
Project: **1bit.systems — One Binary, All Backends, Zero Cloud**
Track: **Track 2 — Development & Local Deployment of Private AI Agents**

---

## Submission Materials

| # | Deliverable | Status | File/Link |
|---|------------|--------|-----------|
| 1 | Project Specification Document | ✅ Complete | `hackathon/spec-document.md` |
| 2 | Project Source Code | ✅ Complete | https://github.com/bong-water-water-bong/1bit-systems |
| 3 | Demo Video | ✅ Complete | `hackathon/demo-video.mp4` (2 min, real commands against the live server — see `hackathon/demo-script.md` for the shot list) |
| 4 | PPT / Poster | ✅ Below | Key slides in this document |

---

## Project Summary (for PR description)

**1bit.systems** is an open-source, single-binary C++ inference engine for AMD Strix Halo (Ryzen AI Max+ 395). It runs private AI agents entirely on-device — no cloud, no API keys, no data exfiltration.

**Key features:**
- **One C++23 binary** — zero Python, zero Docker, zero config
- **Multi-backend**: ROCm HIP (433 tok/s), Vulkan ternary (318 tok/s), XDNA 2 NPU (69 tok/s), CPU fallback
- **Token Router** — dispatches each token to the fastest backend with auto-failover
- **Jarvis Agent** — local agent with RAG, multi-turn memory, tool invocation, multi-step planning, and permission gating (all 5 Track 2 capabilities)
- **40 models** on HuggingFace across 16 families: Qwen3, BlackMamba, Zamba2, Llama 3.1, DeepSeek, Phi-4, Gemma, Mistral, Bonsai, Granite, and more — all in native 1BP format
- **Reverse-engineered** AMD's XDNA 2 NPU in 4 days — 22 proprietary `.so` → 17.5 MB open-source, zero proprietary code
- **OpenAI-compatible API** + A2A protocol

**Hardware**: AMD Ryzen AI Max+ 395 (Strix Halo), Radeon 8060S GPU (gfx1151), 32 XDNA 2 NPU tiles, 128 GB unified LPDDR5X

---

## Poster / Key Slides

### Slide 1: Title
```
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║                   1bit.systems                           ║
║        One Binary to rule them all                       ║
║                                                          ║
║     Pure C++ inference engine · 400 KB · Zero Python     ║
║     NPU + GPU + CPU · Auto-detect · No config            ║
║                                                          ║
║           AMD AI DevMaster Hackathon                     ║
║           Track 2: Private AI Agents                     ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
```

### Slide 2: The Problem
```
Cloud AI agents require:
  ✗ Internet connectivity
  ✗ API keys and billing
  ✗ Data leaving your machine
  ✗ Vendor lock-in
  ✗ Python + Docker + 50 dependencies

Private AI agents should:
  ✓ Run on your hardware
  ✓ Keep your data local
  ✓ Work offline
  ✓ Be one binary to install
  ✓ Use ALL your hardware (GPU + NPU + CPU)
```

### Slide 3: Architecture
```
       ┌──────────┐
       │  Client  │  (1bit Mobile / CLI / curl)
       └────┬─────┘
            │ OpenAI-compatible API
       ┌────▼─────────────────────────────────┐
       │        unified_server (400 KB C++)    │
       │                                       │
       │  Model Router → Token Router →        │
       │  Backend Manager → Jarvis Agent        │
       │                                       │
       │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
       │  │ HIP  │ │ NPU  │ │ Vulk │ │ CPU  │ │
       │  │417/s │ │ 97/s │ │318/s │ │ fall │ │
       │  └──────┘ └──────┘ └──────┘ └──────┘ │
       └──────────────────────────────────────┘
            │                    │
       ┌────▼────┐         ┌────▼────────┐
       │ Radeon  │         │ XDNA 2 NPU  │
       │ 8060S   │         │ 32 tiles    │
       └─────────┘         └─────────────┘
            └───────┬──────────────────────┘
                    │
          128 GB unified LPDDR5X
```

### Slide 4: Performance
```
┌────────────────────────────────────────────┐
│         Kernel-Level Microbenchmarks        │
├────────────────────────────────┬───────────┤
│ Q1 GEMV (HIP fused)           │ 433 tok/s │
│ Fused TQ2 (QKV+GU fused)     │ 420 tok/s │
│ GPU Ternary (Vulkan ZINC)    │ 318 tok/s │
│ NPU v12 (XDNA 2, 32 tiles)   │  69 tok/s │
│ Prefill INT8 WMMA            │ 39.4 TFLOPS │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│         End-to-End Model Inference           │
├────────────────────────────────┬───────────┤
│ BlackMamba 1.5B (Mamba1 HIP)  │ 79.4 t/s  │
│ BlackMamba 2.8B (Mamba1 HIP)  │ 46.0 t/s  │
│ Qwen3 27B Q4_K (spec decode)  │ 30.0 t/s  │
│ Qwen3 35B MoE Q4_K (spec)     │ 20.0 t/s  │
└────────────────────────────────────────────┘

Full breakdown, source-backed: docs/wiki/performance.md
```

### Slide 5: Innovation
```
7 things that didn't exist before this project:

1. Reverse-engineered AMD XDNA 2 NPU — zero docs, 4 days
2. 1BP format — single-file model, 256-byte header
3. 1.58-bit ternary quantization on Vulkan + HIP
4. Token-level multi-backend routing with auto-failover
5. Self-healing agent watchdog
6. Zero-Python inference — C++23 from model to HTTP
7. Exploits Strix Halo unified memory for zero-copy
```

### Slide 6: Get Started
```
One command:

  ./build/unified_server --port 8088

That's it.

  github.com/bong-water-water-bong/1bit-systems
  1bit.systems
  MIT License
```
