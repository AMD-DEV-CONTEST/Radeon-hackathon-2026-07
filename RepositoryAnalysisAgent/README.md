# RepositoryAnalysisAgent (RAA)

> Privacy-first local code repository intelligence agent, optimized for AMD Radeon GPU.

[中文文档](README.zh.md)

---

## What It Does

RAA runs entirely on your local AMD GPU. It indexes a code repository using tree-sitter AST parsing, builds a semantic search index with embedding + cross-encoder reranking, and uses a ReAct agent loop to answer questions about the codebase — all without sending a single line of code to the cloud.

**Capabilities:**
- Repository-level code understanding (cross-file analysis)
- Bug localization and root cause tracing
- Code structure and dependency analysis
- AST-aware semantic search with GPU reranking
- Multi-round ReAct reasoning with tool calls

**What it is NOT:**
- Not a code completion tool (no FIM/autocomplete)
- Not a cloud service (everything runs locally)

---

## Target Environment

| Component | Version |
|---|---|
| GPU | AMD Radeon PRO W7900 (48GB GDDR6, RDNA3 / gfx1100) |
| ROCm | 7.2.1 |
| PyTorch | 2.9 (ROCm build) |
| vLLM | 0.16.0 |
| Python | 3.10 |
| LLM | Qwen2.5-Coder-14B-Instruct (FP16, ~28GB) |
| Embedding | BAAI/bge-m3 (CPU) |
| Reranker | BAAI/bge-reranker-v2-m3 (GPU, ~1.5GB) |

**Docker image (pre-installed PyTorch + vLLM + ROCm):**
```
10.5.10.89:1808/xinwei/radeon-cloud/vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0
```

---

## Quick Start

### 1. Enter the container and clone

```bash
source /opt/venv/bin/activate   # activate the venv with PyTorch + vLLM
cd /workspace
git clone https://github.com/xiting-it/RepoAMD.git
cd RepoAMD
```

### 2. Install app dependencies

```bash
bash setup.sh    # installs deps, removes flash-attn, sets ROCm env vars
```

### 3. Download models

```bash
bash download_models.sh          # all models (~31GB)
# or separately:
bash download_models.sh --rag-only    # embedding + reranker (~3GB)
bash download_models.sh --llm-only    # Qwen 14B (~28GB)
```

### 4. Verify environment

```bash
python scripts/verify_rocm.py
```

All checks should pass (gfx1100, PyTorch ROCm, attention backend, stability, vLLM import).

### 5. Start vLLM (Terminal 1)

```bash
MODEL_PATH=./models/Qwen2.5-Coder-14B-Instruct bash start_llm.sh
```

Wait for `Application startup complete` (~2-4 min cold start).

### 6. Start RAA (Terminal 2)

```bash
python -m src.server /workspace/RepoAMD
```

### 7. Open the web UI

Navigate to `http://127.0.0.1:8080`. Index the repository, then ask questions.

For remote access via SSH tunnel:
```bash
ssh -L 8080:127.0.0.1:8080 root@<server-ip> -p <port>
```

---

## Architecture

```
Browser (localhost:8080)
    │
    ▼
FastAPI Server (src/server.py)
    │
    ├── /api/chat (SSE streaming)
    │       │
    │       ▼
    │   Agent Engine (ReAct loop, max 8 iterations)
    │       │
    │       ├── Context Builder (32K token budget)
    │       ├── Tool Registry
    │       │   ├── search_code  (embedding → GPU rerank → top-15)
    │       │   ├── grep_code    (ripgrep exact/regex)
    │       │   ├── read_file    (line-range reads)
    │       │   ├── get_symbols  (tree-sitter AST)
    │       │   ├── find_references (heuristic symbol lookup)
    │       │   └── run_tests    (disabled by default)
    │       └── LLM Backend (vLLM OpenAI-compatible API)
    │
    ├── /api/index (async background indexing)
    │       │
    │       ▼
    │   Index Pipeline
    │       ├── tree-sitter AST chunk extraction
    │       ├── BGE-m3 embedding (CPU, batch=16)
    │       └── ChromaDB vector store (persistent)
    │
    └── /api/health, /api/sessions, /api/workspace

GPU Memory Layout (48GB total):
  vLLM server:     ~42GB (weights 28 + KV pool 12 + runtime 2)
  Reranker (GPU):   ~1.5GB (model 0.6 + HIP context 0.9)
  Remaining:        ~4.3GB
```

---

## Configuration

All settings in `config.yaml`. Key options:

| Setting | Default | Description |
|---|---|---|
| `server.host` | `127.0.0.1` | Privacy: loopback only |
| `llm.max_model_len` | `32768` | 14B natively supports 128K |
| `llm.gpu_memory_utilization` | `0.88` | 14B FP16 needs ~30GB |
| `llm.enforce_eager` | `true` | gfx1100 HIP graph unstable |
| `embedding.device` | `cpu` | One-time indexing |
| `reranker.device` | `cuda` | Online query hot path |
| `security.run_tests_enabled` | `false` | pytest = arbitrary code execution |

---

## AMD W7900 Optimization

**GDDR6 bandwidth ceiling**: 864 GB/s ÷ 28GB (14B FP16) = ~31 tok/s theoretical max.

**Benchmark results (measured):**

| Metric | Value |
|---|---|
| Single-request throughput | ~8 tok/s |
| 8-way concurrent throughput | ~57 tok/s |
| Time to first token (TTFT) | 0.26s |
| Efficiency vs theoretical | ~27% |

**Key decisions:**
- `enforce_eager=true`: gfx1100 HIP graph capture crashes; costs 10-20% throughput but stable
- FP8 weight/KV cache: unavailable on gfx1100 (vLLM ROCm FP8 kernels target gfx942/MI300X)
- Reranker on GPU: ~0.5s per query vs 4-7s on CPU
- Embedding on CPU: one-time indexing, avoids VRAM contention with vLLM
- ROCm stability vars: `HSA_ENABLE_SDMA=0`, `AMD_SERIALIZE_KERNEL=3`, `AMD_SERIALIZE_COPY=3`

---

## Benchmark & Evaluation

```bash
# Throughput benchmark
python scripts/benchmark.py --base-url http://127.0.0.1:8000/v1

# 20-question quality evaluation (LLM-as-judge)
python scripts/eval_agent.py --app-url http://127.0.0.1:8080
```

---

## Project Structure

```
├── config.yaml              # All configuration
├── start_llm.sh             # vLLM launcher (ROCm env + flags)
├── download_models.sh       # Model downloader (HF mirror / ModelScope)
├── setup.sh                 # One-click environment setup
├── requirements.txt
├── Dockerfile               # Docker packaging
├── src/
│   ├── server.py            # FastAPI entry point
│   ├── config.py            # Config loader
│   ├── backend.py           # LLM backend abstraction
│   ├── tool_parser.py       # Text-based tool call parser
│   ├── agent/               # ReAct engine, prompts, context builder
│   ├── index/               # tree-sitter, embeddings, reranker, ChromaDB
│   ├── tools/               # search, files, AST, exec tools
│   ├── api/                 # FastAPI routes + schemas
│   └── session/             # JSON session persistence
├── scripts/                 # verify_rocm, benchmark, eval_agent
├── static/                  # Web UI (HTML/CSS/JS)
├── tests/                   # 25 unit tests
├── eval/                    # 20-question test set
├── spec.md                  # Product spec (v3.2)
└── plan.md                  # Implementation plan (v3.2)
```

---

## Privacy

- API binds to `127.0.0.1` — no network exposure
- All inference, indexing, and search happen locally
- No telemetry, no external requests
- Verifiable: `tcpdump` shows zero outbound traffic

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `torch.cuda.is_available()` = False | Use `/opt/venv/bin/activate`; verify ROCm wheel |
| vLLM: `No module named 'flash_attn_2_cuda'` | `pip uninstall flash-attn -y` |
| vLLM: Free memory < 42GB | Kill stale processes: `pkill -9 -f vllm`; check `rocm-smi` |
| 400 Bad Request on multi-turn | Update to latest code; context trimming added |
| Model answers in English | Latest prompt enforces Chinese; pull and restart |
| Indexing stuck | Check `chromadb` installed in venv: `pip install chromadb` |

---

## License

MIT
