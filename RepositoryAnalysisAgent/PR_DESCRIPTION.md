# Track 2, RepositoryAnalysisAgent

## Team Name
<!-- Fill in your team name or your personal name -->

## Project Name
RepositoryAnalysisAgent (RAA)

---

## Overview

RepositoryAnalysisAgent is a **privacy-first local code repository intelligence agent** that runs entirely on AMD Radeon PRO W7900 GPU. It uses AST-aware code indexing, semantic retrieval with cross-encoder reranking, and a multi-round ReAct agent to answer questions about codebases — all without sending a single line of code to the cloud.

## Application Scenarios

1. **New developer onboarding** — Understand codebase architecture and structure
2. **Bug localization** — Trace root causes across multiple files
3. **Cross-file impact analysis** — Analyze dependencies and call chains
4. **Security audit** — Locate access controls and identify injection risks
5. **Code review assistance** — Analyze diffs and identify potential risks

## Agent Architecture

```
Browser (localhost:8080)
    │
    ▼
FastAPI Application
    │
    ├── Agent Engine (ReAct loop, max 8 iterations)
    │   ├── Context Builder (32K token budget)
    │   ├── Tool Registry (7 tools: search, grep, read, symbols, references, etc.)
    │   └── LLM Backend (vLLM OpenAI-compatible API)
    │
    ├── Index Pipeline
    │   ├── tree-sitter AST parsing → code chunk extraction
    │   ├── BGE-m3 embedding (CPU) → ChromaDB vector store
    │   └── bge-reranker-v2-m3 (GPU) → top-15 reranked results
    │
    └── Session Manager (JSON persistence)

GPU Memory Layout (48GB):
  vLLM:     ~42GB (weights 28GB + KV pool 12GB + runtime 2GB)
  Reranker:  ~1.5GB (GPU)
  Remaining: ~4.3GB
```

## Core Capabilities

| Capability | Implementation |
|---|---|
| Repository indexing | tree-sitter AST → chunk extraction → BGE-m3 embedding → ChromaDB |
| Semantic search | Embedding retrieval (CPU) → cross-encoder reranking (GPU) |
| Agent reasoning | ReAct loop with text-based tool calling (7 tools) |
| LLM inference | Qwen2.5-Coder-14B-Instruct via vLLM (FP16, 32K context) |
| Web interface | FastAPI + SSE streaming + dark-theme SPA |

## Model Introduction & Local Deployment

| Component | Model | Size | Device |
|---|---|---|---|
| LLM | Qwen2.5-Coder-14B-Instruct | ~28GB (FP16) | GPU (vLLM) |
| Embedding | BAAI/bge-m3 | ~2.4GB | CPU |
| Reranker | BAAI/bge-reranker-v2-m3 | ~0.6GB | GPU |

**Deployment**: Docker-based, using pre-built ROCm 7.2.1 image with PyTorch 2.9 + vLLM 0.16.0. One-click setup script (`setup.sh`) handles venv activation, dependency installation, flash-attn removal, and ROCm environment variables.

## AMD Radeon GPU Optimization

### Throughput Analysis

**GDDR6 bandwidth ceiling**: 864 GB/s ÷ 28GB (14B FP16) ≈ 31 tok/s theoretical maximum.

**Measured benchmark results:**

| Metric | Value |
|---|---|
| Single-request throughput | ~8 tok/s |
| 8-way concurrent throughput | ~57 tok/s |
| Time to first token (TTFT) | 0.26s |

### Optimization Decisions

1. **enforce_eager**: gfx1100 HIP graph capture crashes frequently. Disabled by default (-10~20% throughput but stable).
2. **FP8 unavailable**: RDNA3 WMMA lacks FP8 Matrix Core compute path. vLLM ROCm FP8 kernels target gfx942 (MI300X). Narrative focuses on "FP16 + retrieval strategy".
3. **Reranker on GPU**: Cross-encoder reranking of 20 candidates: <0.5s on GPU vs 4-7s on CPU.
4. **Embedding on CPU**: One-time indexing operation, avoids VRAM contention with vLLM's 42GB allocation.
5. **ROCm stability vars**: `HSA_ENABLE_SDMA=0`, `AMD_SERIALIZE_KERNEL=3`, `AMD_SERIALIZE_COPY=3` fix known gfx1100 race conditions.
6. **flash-attn removal**: Docker image ships CUDA-compiled flash-attn that breaks vLLM on ROCm. Auto-removed in setup.

## Tech Stack

- **GPU**: AMD Radeon PRO W7900 (RDNA3/gfx1100, 48GB GDDR6)
- **Compute**: ROCm 7.2.1 + PyTorch 2.9 + vLLM 0.16.0
- **LLM**: Qwen2.5-Coder-14B-Instruct (FP16)
- **Indexing**: tree-sitter + ChromaDB + BGE-m3
- **Reranking**: bge-reranker-v2-m3 (GPU)
- **Framework**: FastAPI + SSE streaming
- **Language**: Python 3.10

## Source Code

Complete repository: https://github.com/xiting-it/RepoAMD

**Project structure:**
- `src/` — Full application source (agent, index, tools, API, session)
- `scripts/` — Environment verification, benchmark, evaluation tools
- `static/` — Web UI (HTML/CSS/JS)
- `tests/` — 25 unit tests
- `config.yaml` — All configuration
- `Dockerfile` + `docker-compose.yml` — Docker packaging

## Quick Start

```bash
# 1. Setup (in ROCm Docker container)
source /opt/venv/bin/activate
git clone https://github.com/xiting-it/RepoAMD.git
cd RepoAMD && bash setup.sh

# 2. Download models
bash download_models.sh

# 3. Verify environment
python scripts/verify_rocm.py

# 4. Start vLLM (Terminal 1)
MODEL_PATH=./models/Qwen2.5-Coder-14B-Instruct bash start_llm.sh

# 5. Start RAA (Terminal 2)
python -m src.server /path/to/repo

# 6. Open browser
# http://127.0.0.1:8080
```

## Privacy

- API binds to `127.0.0.1` (loopback only)
- All inference, indexing, and search run locally
- No telemetry, no external requests
- Verifiable: `tcpdump` shows zero outbound traffic

## Documentation

- [README.md](README.md) — Quick start guide (EN)
- [README.zh.md](README.zh.md) — Quick start guide (CN)
- [RepositoryAnalysisAgentDoc.md](RepositoryAnalysisAgentDoc.md) — Full technical documentation (EN)
- [RepositoryAnalysisAgentDoc.zh.md](RepositoryAnalysisAgentDoc.zh.md) — Full technical documentation (CN)

## Demo Video

<!-- Add video link here after recording -->
