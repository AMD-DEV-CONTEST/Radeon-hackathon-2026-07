# THEMIS — Technical Requirements Document (TRD)
## Version 1.0 | AMD AI DevMaster Hackathon | July 20, 2026

---

## 1. System Overview

THEMIS is a locally-deployed, multi-service application orchestrating five AI agents to perform autonomous code review. All LLM inference runs on a single AMD Radeon PRO W7900D GPU via the ROCm software stack.

### Core Service Map

```
┌────────────────────────────────────────────────────────┐
│  Client Browser                                        │
│  React 18 + Vite (port 3000)                           │
└──────────────────┬─────────────────────────────────────┘
                   │ HTTP REST + WebSocket
┌──────────────────▼─────────────────────────────────────┐
│  FastAPI Application Server (port 8080)                │
│  Uvicorn + async workers                               │
└───┬──────────────┬─────────────────────────────────────┘
    │              │
┌───▼───┐    ┌─────▼──────────────────────────────────┐
│Qdrant │    │  LangGraph Agent Orchestrator           │
│Vector │    │  (in-process, async)                   │
│DB     │    │  → calls vLLM via OpenAI-compatible API │
│:6333  │    │  → calls Docker SDK for sandboxed tools │
└───────┘    └─────────────────────────────────────────┘
                   │
┌──────────────────▼─────────────────────────────────────┐
│  vLLM Inference Server (port 8000)                     │
│  Qwen2.5-Coder-32B + Qwen2.5-Coder-1.5B (spec decode) │
│  ROCm backend — AMD W7900D 48GB VRAM                   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

### Pinned Versions (requirements.txt)

```
# LLM Inference
vllm==0.6.6.post1           # Last confirmed stable: ROCm + speculative decoding
torch==2.3.0+rocm5.7        # ROCm-patched PyTorch

# Agent Orchestration
langgraph==0.2.28
langchain==0.2.16
langchain-openai==0.1.23    # vLLM uses OpenAI-compatible API

# RAG
qdrant-client==1.11.1
fastembed==0.4.1             # BGE-M3 embedding generation
rank-bm25==0.2.2             # Sparse BM25 retrieval
sentence-transformers==3.0.1 # Cross-encoder reranking

# API & WebSocket
fastapi==0.115.0
uvicorn[standard]==0.30.6
websockets==12.0
python-multipart==0.0.9      # File upload

# GitHub
PyGithub==2.3.0

# Docker SDK (for sandboxed tools)
docker==7.1.0

# Security & Utils
python-dotenv==1.0.1
pydantic==2.8.2
pydantic-settings==2.4.0
httpx==0.27.2
aiofiles==24.1.0

# Data Processing
lxml==5.3.0                  # CWE XML parsing
beautifulsoup4==4.12.3       # OWASP HTML parsing
```

### Frontend Stack (package.json)

```json
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.1",
    "typescript": "^5.5.4",
    "@radix-ui/react-*": "latest",
    "shadcn-ui": "latest",
    "tailwindcss": "^3.4.10",
    "recharts": "^2.12.7",
    "react-diff-view": "^3.2.1",
    "lucide-react": "^0.441.0",
    "framer-motion": "^11.3.31",
    "clsx": "^2.1.1",
    "zustand": "^4.5.5"
  },
  "devDependencies": {
    "vite": "^5.4.2",
    "@vitejs/plugin-react": "^4.3.1"
  }
}
```

### Infrastructure

| Service | Image | Port | Notes |
|---|---|---|---|
| FastAPI backend | `python:3.11-slim` | 8080 | Custom Dockerfile |
| React frontend | `node:20-alpine` | 3000 | Nginx in production |
| Qdrant vector DB | `qdrant/qdrant:v1.11.3` | 6333 | PVC-mounted `/qdrant/storage` |
| vLLM server | `rocm/vllm:latest` | 8000 | Started separately on W7900D |
| Semgrep (sandbox) | `returntocorp/semgrep:1.90.0` | N/A | Ephemeral, Docker-in-Docker |
| Bandit (sandbox) | `pycqa/bandit:1.7.10` | N/A | Ephemeral |
| ESLint (sandbox) | `node:20-alpine` | N/A | Custom image with ESLint pre-installed |

---

## 3. AMD ROCm Infrastructure

### Hardware Specifications

| Component | Specification |
|---|---|
| GPU | AMD Radeon PRO W7900D |
| VRAM | 48 GB GDDR6 |
| Compute | RDNA3 architecture |
| ROCm version | 6.x (per GH-proxy-stable image) |
| Host RAM | Per Radeon Cloud W7900D tier |

### VRAM Budget

| Component | VRAM Usage |
|---|---|
| Qwen2.5-Coder-32B (FP16) | ~37 GB |
| Qwen2.5-Coder-1.5B (FP16, draft) | ~3 GB |
| KV Cache (64K context) | ~5 GB |
| OS/ROCm overhead | ~2 GB |
| **Total at 0.80 utilization** | **~47 GB / 48 GB** |
| **Safety headroom** | **~1 GB** |

> [!CAUTION]
> `gpu-memory-utilization` MUST be 0.80. Using 0.90+ on ROCm causes
> illegal memory access errors and crashes. This was validated in research.

### vLLM Deployment Command (Production-Validated)

```bash
#!/bin/bash
# infra/vllm_deploy.sh

export VLLM_ATTENTION_BACKEND=ROCM_AITER_FA
export VLLM_USE_V1=0
export HF_HOME=/mnt/pvc/models

vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
  --speculative-model Qwen/Qwen2.5-Coder-1.5B-Instruct \
  --num-speculative-tokens 5 \
  --dtype float16 \
  --max-model-len 65536 \
  --gpu-memory-utilization 0.80 \
  --enable-chunked-prefill \
  --speculative-config '{"method": "draft_model", "num_speculative_tokens": 5}' \
  --served-model-name themis-coder \
  --port 8000 \
  --host 0.0.0.0
```

### Environment Variables (Required)

```bash
# .env file (never commit to git)

# GitHub
GITHUB_TOKEN=github_pat_XXXX...

# vLLM
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_MODEL_NAME=themis-coder

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_SECURITY=themis_security
QDRANT_COLLECTION_STYLE=themis_style

# API Security
THEMIS_API_KEY=your_generated_api_key_here

# Storage
PVC_MOUNT=/mnt/pvc
MODELS_DIR=/mnt/pvc/models
DATA_DIR=/mnt/pvc/data

# Application
LOG_LEVEL=INFO
MAX_DIFF_SIZE_BYTES=5242880  # 5MB
MAX_FILES_PER_PR=280
```

---

## 4. Agent Architecture

### LangGraph State Schema

```python
from typing import TypedDict, Annotated, Optional
import operator

class Finding(TypedDict):
    id: str                    # UUID
    type: str                  # "security" | "style"
    severity: str              # "critical" | "high" | "medium" | "low"
    file: str                  # relative file path
    line_start: int
    line_end: int
    title: str
    description: str
    cwe_id: Optional[str]      # e.g. "CWE-89"
    cwe_valid: bool            # validated against lookup
    owasp_ref: Optional[str]   # e.g. "A03:2021"
    rag_citations: list[str]   # retrieved doc excerpts
    tool_source: str           # "semgrep" | "bandit" | "pylint" | "eslint" | "llm"
    confidence: float          # 0.0 – 1.0 (set by Verifier Agent)
    verified: bool             # True if confidence >= 0.7

class Patch(TypedDict):
    file: str
    original_lines: str
    patched_lines: str
    finding_id: str

class ThemisState(TypedDict):
    # ── Input ──────────────────────────────────────
    job_id: str
    input_type: str            # "github_pr" | "file_upload"
    repo: Optional[str]        # "owner/repo"
    pr_number: Optional[int]
    raw_diff: str              # sanitized by sanitizer.py
    files: list[dict]          # [{path, language, content}]

    # ── Triage output ──────────────────────────────
    triage_complete: bool
    prioritized_files: list[dict]
    language_map: dict[str, str]  # {filepath: language}

    # ── Parallel agent outputs (reducer = merge) ───
    security_findings: Annotated[list[Finding], operator.add]
    style_findings: Annotated[list[Finding], operator.add]
    errors: Annotated[list[str], operator.add]

    # ── Verifier output ────────────────────────────
    verified_findings: list[Finding]    # confidence >= 0.7
    low_confidence_findings: list[Finding]

    # ── Fix output ─────────────────────────────────
    patches: list[Patch]
    fix_pr_url: Optional[str]
    fix_approved: bool         # Human-in-the-loop gate

    # ── Metadata ───────────────────────────────────
    visited_tool_hashes: set[str]
    step_count: int
    started_at: str            # ISO timestamp
    completed_at: Optional[str]
    total_tokens_used: int
```

### Agent Execution Flow

```
START
  │
  ▼
① TRIAGE AGENT
  - Sanitize diff (sanitizer.py)
  - Detect languages per file
  - Score files by risk surface (exec code > config > tests)
  - Chunk large diffs (8K token windows)
  - Output: prioritized_files, language_map
  │
  ├──────────────────────┐ (parallel fan-out)
  │                      │
  ▼                      ▼
② SECURITY AGENT       ③ STYLE AGENT
  - Run Semgrep          - Select linter by language
    (Docker sandbox)       (Pylint for Python,
  - Run Bandit             ESLint for JS/TS)
    (Docker sandbox)     - Run in Docker sandbox
  - Validate results     - Retrieve style guide
  - RAG: OWASP + CWE       context via RAG
  - LLM synthesis        - LLM synthesis
  - Output: security_    - Output: style_
    findings               findings
  │                      │
  └──────────┬───────────┘ (parallel fan-in, reducer merges)
             │
             ▼
         ④ VERIFIER AGENT
           - For each finding:
             • RAG cross-check citation
             • Validate CWE ID vs lookup
             • Score confidence 0.0–1.0
             • Filter: confidence < 0.7 → low_confidence_findings
           - Output: verified_findings
             │
             ▼
         HUMAN APPROVAL GATE ◄─── Pause here
           - Frontend shows verified findings
           - User reviews and approves/rejects
           - fix_approved = True → continue
           - fix_approved = False → terminate (report only)
             │
             ▼
         ⑤ FIX AGENT
           - Generate patch for each verified finding
           - Create branch: themis/fix-pr-{pr_number}
           - Commit patches
           - Open counter-PR with structured body
           - Output: patches, fix_pr_url
             │
             ▼
           END
```

---

## 5. RAG Architecture

### Qdrant Collections

```
Collection: themis_security
  - Vectors: BGE-M3 (1024 dimensions)
  - Payload: {source, cwe_id, owasp_ref, title, content, url}
  - Indexed: OWASP Top 10 2021, CWE Top 25, NIST SARD
  - Sparse vectors: BM25 (Qdrant native sparse)

Collection: themis_style
  - Vectors: BGE-M3 (1024 dimensions)
  - Payload: {source, language, rule_id, title, content, url}
  - Indexed: PEP 8, Google Python Style, Google JS Style, ESLint rules
  - Sparse vectors: BM25
```

### Retrieval Pipeline

```python
async def retrieve(query: str, collection: str, top_k: int = 5) -> list[dict]:
    # Step 1: BGE-M3 dense embedding (on CPU to preserve GPU VRAM)
    dense_vector = embedder.embed(query)  # 1024-dim float32

    # Step 2: BM25 sparse vector
    sparse_vector = bm25_encode(query)

    # Step 3: Qdrant hybrid search (RRF fusion)
    candidates = qdrant_client.search(
        collection_name=collection,
        query_vector=dense_vector,
        query_sparse_vector=sparse_vector,
        limit=20  # Over-fetch for reranking
    )

    # Step 4: Cross-encoder reranking (ms-marco-MiniLM-L-6-v2)
    reranked = cross_encoder.rerank(query, [c.payload["content"] for c in candidates])

    # Step 5: Return top-k
    return reranked[:top_k]
```

### Knowledge Base Indexing

```bash
# infra/index_knowledge.sh
#!/bin/bash
# Run once on first deployment, results persist on PVC Qdrant storage

echo "Indexing OWASP Top 10..."
python backend/rag/indexer.py --source owasp --data-dir /mnt/pvc/data/owasp --collection themis_security

echo "Indexing CWE XML..."
python backend/rag/indexer.py --source cwe --data-dir /mnt/pvc/data/cwe --collection themis_security

echo "Indexing style guides..."
python backend/rag/indexer.py --source style --data-dir /mnt/pvc/data/style --collection themis_style

echo "Indexing complete. Collections ready."
```

---

## 6. API Contract

### Authentication

All endpoints require `X-API-Key` header matching `THEMIS_API_KEY` env var.

```http
X-API-Key: your_generated_api_key_here
```

Returns `401 Unauthorized` if missing or invalid.

### Endpoints

#### `POST /api/review/github`
Submit a GitHub PR for review.

**Request:**
```json
{
  "repo": "owner/repository",
  "pr_number": 42
}
```
**Response `202 Accepted`:**
```json
{
  "job_id": "uuid-v4",
  "status": "queued",
  "stream_url": "ws://host/api/review/{job_id}/stream"
}
```

---

#### `POST /api/review/upload`
Submit code files for review (multipart form).

**Request:** `multipart/form-data` with one or more files.

**Response `202 Accepted`:**
```json
{
  "job_id": "uuid-v4",
  "status": "queued",
  "stream_url": "ws://host/api/review/{job_id}/stream"
}
```

---

#### `GET /api/review/{job_id}/status`
Poll job status.

**Response `200 OK`:**
```json
{
  "job_id": "uuid-v4",
  "status": "running",           // queued | running | awaiting_approval | complete | error
  "current_agent": "security",
  "progress_pct": 40,
  "started_at": "2026-07-20T12:00:00Z"
}
```

---

#### `WS /api/review/{job_id}/stream`
WebSocket stream of live agent trace events.

**Event format:**
```json
{
  "event": "agent_step",
  "agent": "security",
  "step": "semgrep_complete",
  "message": "Semgrep found 3 potential issues",
  "timestamp": "2026-07-20T12:00:05Z",
  "data": {}
}
```

**Event types:**
- `agent_started` — agent began processing
- `tool_call` — sandboxed tool invoked
- `tool_result` — tool returned result
- `rag_retrieved` — RAG citations fetched
- `agent_complete` — agent finished, findings ready
- `awaiting_approval` — Fix Agent paused for human gate
- `pipeline_complete` — full pipeline done

---

#### `GET /api/review/{job_id}/report`
Get the structured findings report.

**Response `200 OK`:**
```json
{
  "job_id": "uuid-v4",
  "status": "complete",
  "summary": {
    "total_findings": 12,
    "critical": 2,
    "high": 4,
    "medium": 4,
    "low": 2,
    "low_confidence_filtered": 3
  },
  "verified_findings": [/* array of Finding objects */],
  "low_confidence_findings": [/* filtered findings */],
  "patches_available": true,
  "fix_pr_url": null,
  "benchmark_tokens_used": 14520,
  "elapsed_seconds": 87
}
```

---

#### `POST /api/review/{job_id}/approve-fix`
Human approval gate — trigger Fix Agent to open the counter-PR.

**Request:**
```json
{ "approved": true }
```

**Response `200 OK`:**
```json
{
  "status": "fix_pr_opening",
  "branch": "themis/fix-pr-42"
}
```

---

#### `GET /api/benchmark`
Run the ROCm inference benchmark suite.

**Response `200 OK`:**
```json
{
  "model": "Qwen2.5-Coder-32B-Instruct",
  "hardware": "AMD Radeon PRO W7900D",
  "rocm_version": "6.x",
  "results": {
    "throughput_batch1": 48.2,
    "throughput_batch4": 112.7,
    "ttft_4k_ms": 1240,
    "ttft_16k_ms": 3100,
    "speculative_decoding_speedup": 1.87,
    "int4_throughput_batch1": 71.3,
    "int4_vs_fp16_delta_pct": 47.9
  },
  "timestamp": "2026-07-20T14:00:00Z"
}
```

---

#### `GET /health`
Health check — verifies vLLM and Qdrant connectivity.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "vllm": "connected",
  "qdrant": "connected",
  "gpu_vram_used_gb": 40.1,
  "gpu_vram_total_gb": 48.0
}
```

---

## 7. Security Architecture

### Threat Model

| Threat | Mitigation |
|---|---|
| Prompt injection via PR diff | Regex sanitizer + code fence wrapping |
| RCE via malicious code in sandboxed tool | Docker: no network, read-only FS, mem cap |
| Unauthorized API access | `X-API-Key` header required |
| GITHUB_TOKEN exposure in logs | Token masked in all log outputs |
| CWE hallucination | Static lookup validation before citation |
| Cross-request state leakage | Per-request LangGraph state, MemorySaver scoped to job_id |
| Agent infinite loops | recursion_limit=30, SHA-256 tool call dedup |
| Large PR diff OOM | Diff chunked to 8K token windows |

### Secret Management

```bash
# Required env vars — load from .env with python-dotenv
# NEVER hardcode in source code
# NEVER commit .env to git (add to .gitignore)

GITHUB_TOKEN         # Fine-grained PAT (already set)
THEMIS_API_KEY        # Generated: openssl rand -hex 32
QDRANT_API_KEY        # Optional: if Qdrant auth enabled
```

---

## 8. Performance Requirements & Benchmarks

### Benchmark Test Suite (10 standard prompts)

```python
BENCHMARK_PROMPTS = [
    # Security analysis prompts (4K, 8K, 16K, 32K context)
    {"id": "sec_4k",   "context_tokens": 4000,  "type": "security_analysis"},
    {"id": "sec_8k",   "context_tokens": 8000,  "type": "security_analysis"},
    {"id": "sec_16k",  "context_tokens": 16000, "type": "security_analysis"},
    {"id": "sec_32k",  "context_tokens": 32000, "type": "security_analysis"},
    # Fix generation prompts
    {"id": "fix_2k",   "context_tokens": 2000,  "type": "fix_generation"},
    {"id": "fix_8k",   "context_tokens": 8000,  "type": "fix_generation"},
    # Speculative decoding comparison
    {"id": "spec_on",  "context_tokens": 4000,  "speculative": True},
    {"id": "spec_off", "context_tokens": 4000,  "speculative": False},
    # INT4 vs FP16
    {"id": "int4",     "context_tokens": 4000,  "quantization": "int4"},
    {"id": "fp16",     "context_tokens": 4000,  "quantization": "fp16"},
]
```

### Performance Targets

| Metric | Target | Stretch |
|---|---|---|
| tok/s (batch 1, FP16) | >45 | >60 |
| tok/s (batch 4, FP16) | >100 | >140 |
| TTFT @ 4K context | <2s | <1s |
| TTFT @ 16K context | <5s | <3s |
| Speculative decoding speedup | >1.5× | >2.0× |
| INT4 throughput gain | >30% | >50% |
| Full PR pipeline (50 files) | <120s | <60s |

---

## 9. Monitoring & Observability

### GPU Monitoring (during demo)

```bash
# Terminal 1: real-time GPU stats
watch -n 1 rocm-smi --showuse --showmemuse --showtemp

# Terminal 2: vLLM server logs
tail -f /mnt/pvc/logs/vllm.log
```

### Application Logging

```python
# backend/config.py
import logging

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/mnt/pvc/logs/themis.log")
    ]
)

# Mask sensitive data
class TokenMaskingFilter(logging.Filter):
    def filter(self, record):
        record.msg = str(record.msg).replace(
            os.getenv("GITHUB_TOKEN", ""), "[TOKEN_MASKED]"
        )
        return True
```

---

## 10. Deployment Architecture

### Radeon Cloud Deployment

```
Radeon Cloud W7900D Instance (GH-proxy-stable)
├── /mnt/pvc/                    ← Persistent Volume Claim
│   ├── models/
│   │   ├── qwen32b/             ← ~65GB model weights
│   │   ├── qwen1.5b/            ← ~3GB draft model
│   │   └── bge-m3/              ← ~2GB embedding model
│   ├── data/
│   │   ├── owasp/
│   │   ├── cwe/
│   │   └── style/
│   ├── qdrant-storage/          ← Qdrant persistent data
│   └── logs/
│
├── vllm server (foreground, port 8000)
└── docker-compose up
    ├── qdrant (port 6333)
    ├── backend (port 8080)
    └── frontend (port 3000)
```

### docker-compose.yml

```yaml
version: "3.9"
services:
  qdrant:
    image: qdrant/qdrant:v1.11.3
    ports:
      - "6333:6333"
    volumes:
      - /mnt/pvc/qdrant-storage:/qdrant/storage
    restart: unless-stopped

  backend:
    build: ./backend
    ports:
      - "8080:8080"
    env_file: .env
    volumes:
      - /mnt/pvc:/mnt/pvc
      - /var/run/docker.sock:/var/run/docker.sock  # Docker-in-Docker for sandboxing
    depends_on:
      - qdrant
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend
    restart: unless-stopped
```

> [!WARNING]
> Mounting `/var/run/docker.sock` is required for Docker-in-Docker sandbox execution.
> This is safe in our deployment context (single-user, controlled environment)
> but would need a proper container runtime in production.
