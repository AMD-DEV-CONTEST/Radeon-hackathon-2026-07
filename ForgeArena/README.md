# ForgeArena ⚡

> Multi-Agent Decision Simulation Platform  
> AMD AI DevMaster Hackathon 2026 · Track 2: Private AI Agent Development  
> Built on AMD Radeon GPU + ROCm + vLLM

ForgeArena is a **locally deployed, multi-agent decision-making system** where multiple AI agents with distinct cognitive biases reason, call tools, and make decisions autonomously — powered entirely by Qwen2.5-7B running on AMD Radeon GPU via vLLM ROCm.

## Architecture

```
User Input → Scenario Description
                ↓
          Agent Orchestrator
        ┌───────┼───────┐
    Conservative  Aggressive  Explorer
    (risk-averse) (optimizer) (adaptive)
        │          │          │
        └──────────┼──────────┘
                   ↓
           Decision Synthesis
                   ↓
          Final Recommendation
```

## Features

| Capability | Status |
|-----------|--------|
| Multi-step task planning | ✅ 6-stage sandbox pipeline |
| Tool calling | ✅ ToolRouter: simulate / retrieve / query |
| Local RAG (knowledge retrieval) | ✅ Policy Library (946 entries) |
| Multi-turn memory | ✅ Agent Memory with historical recall |
| Privacy & permission control | ✅ Fully local, zero data egress |
| AMD ROCm inference | ✅ Qwen2.5-7B @ 87.5 t/s on Radeon 48GB |

## Quick Start

### 1. Prerequisites

- AMD Radeon GPU + ROCm 7.2+
- Python 3.10+
- 16GB+ VRAM recommended

### 2. Install

```bash
git clone https://github.com/yyf121381/forgearena.git
cd forgearena
pip install -r requirements.txt
```

### 3. Setup Model

```bash
# Option A: Download via ModelScope (recommended in China)
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('qwen/Qwen2.5-7B-Instruct')"

# Option B: Download via HuggingFace
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-7B-Instruct')"
```

### 4. Run

```bash
# 1. Start vLLM server
export MODEL_PATH=/path/to/Qwen2.5-7B-Instruct
vllm serve $MODEL_PATH --host 0.0.0.0 --port 8000 --dtype half --gpu-memory-utilization 0.85 --trust-remote-code

# 2. Start ForgeArena GPT Architecture UI (recommended)
#    Three AI advisor cards + structured decision report + evidence layer
export VLLM_API=http://localhost:8000/v1/chat/completions
export MODEL_PATH=$MODEL_PATH
python forgearena_chat.py
# Open http://localhost:24573

# Or use Flask web UI (alternative)
python forgearena_ui.py
# Open http://localhost:24680
```

## Benchmark (AMD Radeon RDNA3 48GB)

| Metric | Value |
|--------|-------|
| Model | Qwen2.5-7B-Instruct |
| Backend | vLLM 0.23.1 ROCm |
| Avg. Throughput | 87.5 tokens/s |
| 3-Agent Parallel Efficiency | 2.27× vs sequential |
| GPU Memory | ~42GB / 48GB (85%) |

## Project Structure

```
forgearena/
├── forgearena.py           ← Core framework (Agent, ToolRouter, Manager)
├── forgearena_ui.py        ← Web UI (Flask + HTML)
├── forgearena_chat.py       ← GPT architecture UI (main submission)
├── tools.py                ← Tool Router (simulate, retrieve, memory)
├── perception.py           ← WorldState perception
├── 02_deploy_amd.py        ← AMD deployment script
├── 03_run_demo.py          ← Full pipeline runner
├── ablation.py / v2.py     ← Ablation experiments (personality attribution)
├── policies/               ← Strategy policy library
├── FORGEARENA_REPORT.md    ← Competition report (Chinese)
├── start_vllm.sh           ← One-click vLLM startup
└── requirements.txt
```

## License

MIT
