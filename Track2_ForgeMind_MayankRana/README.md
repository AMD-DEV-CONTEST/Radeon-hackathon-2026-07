# ForgeMind — Offline Sovereign Developer Swarm on AMD Radeon™ + ROCm

> **Track 2: Localized AI Agents Deployment | AMD AI DevMaster Hackathon 2026**

[![ROCm](https://img.shields.io/badge/ROCm-6.2+-red?logo=amd)]()
[![Radeon](https://img.shields.io/badge/Runs%20On-Radeon%20RX%207900%20%2F%20PRO%20W7900-black)]()
[![Local](https://img.shields.io/badge/100%25-Local%20%7C%20Offline-green)]()
[![Agents](https://img.shields.io/badge/Agents-5%20Autonomous-blue)]()

**ForgeMind is a 100% offline, multi-agent software engineering swarm that lives entirely on your AMD Radeon GPU. No OpenAI keys. No cloud. No data leakage.**

Give it a codebase + a task: *"Add JWT auth to this Flask app and write tests"* — it will autonomously Plan → Code → Test → Review → Document, all with local LLMs accelerated by ROCm + vLLM/Ollama.

### 🎯 Problem
- Developers can't send proprietary code to cloud LLMs (IP risk)
- Cloud coding assistants cost $$$, need internet, have latency
- Consumer Radeon GPUs are underutilized for agentic AI — most agents assume NVIDIA/CUDA
- Single-agent coding assistants hallucinate and don't self-test

### 💡 Solution: ForgeMind
A **Sovereign Multi-Agent System** running entirely on **AMD Radeon + ROCm**:

| Agent | Role | Tools |
|-------|------|-------|
| **Planner** | Breaks task into DAG, reasons over codebase | RAG, file_tree |
| **Coder** | Writes/edits code with ROCm-accelerated Qwen2.5-Coder | code_read, code_write |
| **Tester** | Generates pytest, runs in sandbox, fixes failures | terminal, test_runner |
| **Reviewer** | Security + quality review, suggests improvements | code_read, static_analysis |
| **DocWriter** | Generates README updates, docstrings, changelog | code_read, doc_gen |

All orchestrated via **LangGraph StateGraph** with shared memory, running on **local LLMs via vLLM-ROCm / Ollama-ROCm**.

### 🏗️ Architecture

```
[User Task] → [Gradio UI + FastAPI]
       ↓
[Codebase Ingestion] → Tree-sitter Chunking → BGE-Base Embeddings (local) → ChromaDB
       ↓
[LangGraph Swarm - Shared State]
  Planner → Coder → Tester (loop until pass) → Reviewer → DocWriter
       ↓ Each agent uses:
  [LLM_ROCM Layer] → vLLM-ROCm (Qwen2.5-Coder-7B, 4-bit AWQ) + FlashAttention-2 on RDNA3
       ↓
[Tools] file_tools, terminal_tool (sandboxed), rag_tool
       ↓
[ROCm Monitor] rocm-smi, GPU util, VRAM, temp → UI Dashboard
```

**ROCm Optimizations:**
1.  vLLM with ROCm backend: `--dtype=half --enforce-eager --max-model-len=8192`
2.  AWQ 4-bit quantization: 7B model fits in 8GB VRAM (RX 7600+) , 14B in 24GB (RX 7900 XTX)
3.  FlashAttention-2 for RDNA3, ROCm 6.2+ PyTorch
4.  Continuous batching + PagedAttention for multi-agent concurrency
5.  Ollama ROCm fallback for easy setup on consumer Radeon

### 🎬 Demo Video
  Video: https://drive.google.com/file/d/1mQwuaIh26JKDF-1JFYR9BrQhq1AOHPLX/view?usp=sharing

### ⚡ Why Radeon + ROCm?
- **Privacy**: Air-gapped development for defense, finance, healthcare code
- **Cost**: One-time GPU cost vs $20/mo per dev for Copilot
- **Latency**: <50ms token latency on RX 7900 XTX, no network hop
- **Sovereignty**: No dependency on US cloud providers — runs in India/EU/China local
- **Performance**: Qwen2.5-Coder-7B @ 68 tok/s on RX 7900 XTX (vLLM-ROCm)

### 🚀 Quick Start (AMD Radeon + ROCm)

#### Option 1: Native ROCm (Recommended for Judges)

```bash
# 1. Install ROCm 6.2+ (Ubuntu 22.04)
# See https://rocm.docs.amd.com/

# 2. Setup
git clone https://github.com/your-username/forgemind
cd forgemind
chmod +x setup_rocm.sh
./setup_rocm.sh

# 3. Pull model with Ollama ROCm
ollama serve &
ollama pull qwen2.5-coder:7b
# or for more VRAM: ollama pull qwen2.5-coder:14b

# 4. Run
pip install -r requirements.txt
python app/main.py --model qwen2.5-coder:7b --rocm

# Open http://localhost:7860
```

#### Option 2: Docker ROCm (One-Click)

```bash
cd docker
docker compose up --build
# Downloads rocm/pytorch:rocm6.2, builds vLLM-ROCm, starts UI on :7860
```

### 📊 Benchmarks (RX 7900 XTX)

| Metric | vLLM-ROCm (Qwen-7B AWQ) | Ollama-ROCm |
|--------|------------------------|-------------|
| Tokens/sec | 68.4 | 52.1 |
| TTFT | 180ms | 320ms |
| VRAM | 5.8GB | 6.1GB |
| Task Success (HumanEval) | 71% | 69% |

Run: `python benchmarks/rocm_bench.py`

### 📁 Repo Structure
```
forgemind/
├── app/
│   ├── main.py (FastAPI + Gradio entry)
│   ├── rocm_utils.py (GPU detection)
│   ├── agents/ (LangGraph multi-agent swarm)
│   ├── tools/ (file, terminal, RAG)
│   ├── models/ (ROCm LLM abstraction)
│   └── ui/ (Gradio dashboard)
├── docker/Dockerfile.rocm
├── demo/
└── benchmarks/
```

### 🔮 Future
- Integration with Ryzen AI NPU for agent routing
- Support for 7900 + MI300X heterogeneous swarm
- VSCode extension: offline Copilot replacement

### 👥 Team
Built for AMD AI DevMaster Hackathon 2026 — Track 2 Localized AI Agents

**License:** MIT
**Requires:** AMD Radeon RX 7000+ / PRO W7000+, ROCm 6.2+, 16GB RAM
