# Track 2 Submission: Memloom

**Team:** memloom  
**Application:** Memloom — a local private AI agent knowledge layer  
**Source Code:** https://github.com/Moonfall-Lab/memloom (private, access upon request)

## Submission Materials

| Item | File | Notes |
|---|---|---|
| Project Specification | [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) | Scenarios, architecture, core capabilities, model deployment, AMD optimization |
| Demo Video (4:55, English) | [demo.mp4](demo.mp4) | Actual operation on AMD Radeon GPU (gfx1100, ROCm 7.2.1) |
| Slide Deck | [Memloom-5min-EN.pptx](Memloom-5min-EN.pptx) | 5-minute presentation |
| Architecture Diagram | [agent-architecture.md](agent-architecture.md) + [assets/agent-architecture.svg](assets/agent-architecture.svg) | Mermaid + SVG |
| Inference Optimization | [amd-radeon-gpu-inference-optimization.md](amd-radeon-gpu-inference-optimization.md) | vLLM tuning, flash-attn fix, 14-model benchmark |
| English README | [README.en.md](README.en.md) | Environment setup & startup guide |

## Quick Stats

- **GPU:** AMD gfx1100 (RDNA3), 51.52 GB VRAM
- **ROCm:** 7.2.1
- **Models tested:** 14 (Qwen2.5-14B, Qwen3-14B, etc.)
- **TTFT improvement:** 236× (vLLM vs naive loading)
- **Throughput:** 2× higher, VRAM efficiency: 6.1×
- **Benchmark:** v2 stateful 5-dimension evaluation suite (extraction + governance + lifecycle + reuse + local evidence)

## How to Run (Local AMD GPU)

```bash
# 1. Install dependencies
cd zhiyi-desktop && npm install

# 2. Start local vLLM (AMD ROCm)
/opt/venv/bin/vllm serve Qwen2.5-14B-Instruct \
  --dtype bfloat16 --max-model-len 8192 --gpu-memory-utilization 0.95 \
  --enforce-eager --tensor-parallel-size 1

# 3. Launch Memloom desktop client
npm start
