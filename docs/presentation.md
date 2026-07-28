# OmniKernel-ROCm: Presentation Deck

> **AMD AI DevMaster Hackathon 2026 · Track 2 (Private AI Agents)**  
> **Supplementary Submission Item: Project Slide Deck / Poster**

---

## 📊 Slide 1: Title & Vision

### 🔥 OmniKernel-ROCm
**Local, Conversational GPU Performance-Diagnosis Agent for AMD ROCm/HIP Workloads**

* **Track:** Track 2 — Development & Local Deployment of Private AI Agents
* **Target Hardware:** AMD Radeon RX 7900 XTX (RDNA3 Architecture)
* **Core Philosophy:** 100% On-Device, Privacy-First, Evidence-Cites Reasoning — The Agent Proposes, You Approve
* **Demo Video:** https://youtu.be/PjHsIE9IJfg
* **Presentation Deck (PPT):** https://drive.google.com/file/d/1ylwZHsjMGFtfPJhNa8QEHATWk6-YKSLC/view?usp=sharing

---

## 🎯 Slide 2: The Problem & Application Scenario

### The Problem: CUDA-to-ROCm Performance Regressions
* **The Performance Cliff:** Porting CUDA kernels to AMD ROCm/HIP often results in 2× to 5× unexpected performance regressions.
* **Buried Root Causes:** Bottlenecks like uncoalesced memory access, LDS bank conflicts, and wavefront stalling are hidden across three disconnected sources:
  1. rocm-smi hardware utilization figures
  2. torch.profiler call timelines and operator traces
  3. Scattered ROCm architecture manuals and HIP porting guides
* **The Manual Bottleneck:** Diagnosing a single regression requires an experienced ROCm engineer hours to manually correlate tools, form a hypothesis, write a patch, and benchmark.

### The Solution: OmniKernel-ROCm
An AI pair-programmer that inspects live GPU data, searches a local ROCm knowledge base, proposes non-invasive fixes, and defends or revises its hypothesis when challenged.

---

## 🏗️ Slide 3: System Architecture & Core Capabilities

`
┌──────────────────────────────────────────────────────────────────┐
│                   Developer (Web UI / CLI)                        │
└───────────────────────────────┬──────────────────────────────────┘
                                │ prompt / pushback
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│              Orchestrator & Pushback Loop Manager                │
└──────┬──────────────┬──────────────┬──────────────┬──────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
 ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌────────────────┐
 │   Tools   │  │    RAG    │  │  Memory   │  │Permission Gate │
 │ rocm-smi  │  │ 371-chunk │  │  SQLite   │  │  Propose-only  │
 │ profiler  │  │  HIP doc  │  │  history  │  │  Audit JSONL   │
 └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────────────────┘
       │              │              │
       └──────────────┼──────────────┘
                      ▼
 ┌─────────────────────────────────────────┐
 │          Planner & Local LLM            │
 │ Qwen2.5-Coder on AMD Radeon RX 7900 XTX │
 └─────────────────────────────────────────┘
`

### 5 Core Capabilities Implemented:
1. **Task Decomposition & Tool Layer:** JSON tool pipeline (rocm-smi, torch.profiler, sandbox benchmark, diff proposer).
2. **RAG Grounded Retrieval:** 371 section-indexed chunks from full AMD HIP Programming Guide (5,619 lines).
3. **Multi-Turn Pushback Loop:** Adversarial re-examination that re-invokes tools when challenged.
4. **Cross-Session SQLite Memory:** Remembers which optimization patterns succeeded on specific codebases.
5. **Structural Safety:** Propose-only Permission Gate with append-only audit logging (omnikernel_audit.jsonl).

---

## ⚡ Slide 4: Real AMD Hardware Benchmarks

### Signature Case: 8192×8192 Matrix Memory Coalescing

| Metric | Baseline (Strided Access) | Candidate (Coalesced Access) | Improvement |
|---|---|---|---|
| **Kernel Latency** | 10.13 ms | 6.85 ms | **1.48× Speedup (~48% faster)** |
| **Wavefront Behavior** | 64 transactions per iteration | 1 coalesced burst per iteration | **64× transaction reduction** |
| **System Test Suite** | 63 / 63 passed | 63 / 63 passed | **0.92s execution time** |

> **Hardware Testbed:** AMD Radeon RX 7900 XTX / Navi 31 (0x744b) via Radeon Cloud  
> **Environment:** PyTorch 2.9.1+gitff65f5b (ROCm) | vLLM 0.16.1

---

## 🔒 Slide 5: Local AI Inference & Speed Optimization

### On-Device Inference Engine (100% Private)
* **Model:** Qwen2.5-Coder-1.5B–7B-Instruct served via vLLM on ROCm backend.
* **Zero External Calls:** Core reasoning executes locally on AMD Radeon GPU VRAM.

### Inference Speed Optimizations Applied:
* **AWQ 4-bit Quantization:** ~3× VRAM reduction with negligible quality loss on code tasks.
* **Continuous Batching & Prefix Reuse:** vLLM default scheduler eliminates prefix recomputation across turns.
* **ROCm-Native Attention (TORCH_SDPA):** VLLM_ATTENTION_BACKEND=TORCH_SDPA eliminates CUDA-only dependencies.
* **Low-Temperature Decoding (temp=0.2):** 20–30% lower per-token latency for structured JSON generation.

---

## 🏆 Slide 6: Business Impact & Conclusion

### Value Delivered to AMD Ecosystem:
* **Accelerates CUDA-to-ROCm Porting:** Reduces diagnostic turn-around from hours to seconds.
* **Enterprise Privacy:** Zero cloud API dependencies — code and profiling metrics never leave local infrastructure.
* **Verifiable & Reproducible:** Includes automated setup script (scripts/setup_radeon_cloud.sh), Gradio Web UI (src/ui.py), and 63 unit tests.

> **OmniKernel-ROCm: Bringing Enterprise-Grade, Evidence-Grounded AI Pair Programming Directly to AMD Hardware.**
