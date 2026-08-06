# RepositoryAnalysisAgent — Technical Documentation

> Version: 1.0 | Date: 2025-08-05
> Target: AMD Radeon PRO W7900 (48GB GDDR6, RDNA3 / gfx1100)
> [中文技术文档](RepositoryAnalysisAgentDoc.zh.md)

---

## 1. System Overview

### 1.1 What RAA Does

RepositoryAnalysisAgent (RAA) is a privacy-first, fully local code repository intelligence system. It combines AST-aware code indexing, semantic retrieval with cross-encoder reranking, and a multi-round ReAct agent to answer questions about codebases — all running on a single AMD Radeon PRO W7900 GPU with zero data leaving the machine.

### 1.2 Core Capabilities

| Capability | Implementation |
|---|---|
| Repository indexing | tree-sitter AST parsing → chunk extraction → embedding → ChromaDB |
| Semantic search | BGE-m3 embedding (CPU) → top-20 candidates → bge-reranker (GPU) → top-15 |
| Agent reasoning | ReAct loop (max 8 iterations) with 7 tools |
| LLM inference | vLLM serving Qwen2.5-Coder-14B-Instruct (FP16, 32K context) |
| Web interface | FastAPI + SSE streaming + dark-theme SPA |

### 1.3 Application Scenarios

1. **New developer onboarding** — "What does this codebase do? How is it structured?"
2. **Bug localization** — "Where is the authentication bug? Trace the root cause."
3. **Cross-file impact analysis** — "If I change this function, what breaks?"
4. **Code review assistance** — "What are the risks in this git diff?"
5. **Security audit** — "Where are the file access controls? Any injection risks?"

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   User (Browser, localhost)                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (127.0.0.1:8080)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Application                        │
│                                                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌───────────────┐ │
│  │ /chat   │  │ /index  │  │ /health  │  │ /workspace    │ │
│  │ (SSE)   │  │ (async) │  │          │  │ /sessions     │ │
│  └────┬────┘  └────┬────┘  └──────────┘  └───────────────┘ │
│       │            │                                         │
│  ┌────▼────────────▼────────────────────────────────────┐   │
│  │              Agent Engine (ReAct)                     │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │ Context    │  │ Tool Registry│  │ LLM Backend  │  │   │
│  │  │ Builder    │  │ (7 tools)    │  │ (vLLM HTTP)  │  │   │
│  │  └────────────┘  └──────────────┘  └──────┬───────┘  │   │
│  └───────────────────────────────────────────┼──────────┘   │
│                                              │               │
│  ┌───────────────────────────────────────────▼──────────┐   │
│  │              Index Subsystem                           │   │
│  │  tree-sitter → BGE-m3 (CPU) → ChromaDB                 │   │
│  │                                    bge-reranker (GPU)   │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              AMD W7900 GPU (48GB GDDR6)                      │
│                                                              │
│  Process 1: vLLM server     ~42GB VRAM                       │
│    Weights (14B FP16): 28GB | KV pool: 12GB | Runtime: 2GB  │
│                                                              │
│  Process 2: Reranker (GPU)   ~1.5GB VRAM                     │
│    Model: 0.6GB | HIP context + allocator: 0.9GB            │
│                                                              │
│  CPU: BGE-m3 embedding (indexing only)                       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Component Dependency Graph

```
server.py
  ├── config.py (Config loader)
  ├── backend.py (LLM HTTP client)
  ├── api/routes.py (FastAPI routes)
  │   └── api/schemas.py (Pydantic models)
  ├── agent/engine.py (ReAct loop)
  │   ├── agent/context.py (Token budget management)
  │   ├── agent/prompts.py (System prompt)
  │   └── tool_parser.py (Text-based tool call extraction)
  ├── tools/registry.py (Tool dispatch)
  │   ├── tools/search.py (search_code + grep_code)
  │   ├── tools/files.py (read_file + list_directory)
  │   ├── tools/ast_tools.py (get_symbols + find_references)
  │   └── tools/exec.py (run_tests)
  ├── index/indexer.py (Pipeline coordinator)
  │   ├── index/parser.py (tree-sitter AST)
  │   ├── index/embeddings.py (BGE-m3 CPU)
  │   ├── index/reranker.py (bge-reranker GPU)
  │   └── index/vector_store.py (ChromaDB)
  └── session/manager.py (JSON persistence)
```

---

## 3. Agent Engine

### 3.1 ReAct Loop

The agent uses a ReAct (Reasoning + Acting) loop with text-based tool calling:

```
User Query
    │
    ▼
┌─────────────────┐
│ Context Builder │ ── system prompt + repo tree + history
└────────┬────────┘
         │
    ┌────▼─────────────────────────────┐
    │      Iteration 1..8               │
    │                                   │
    │  1. Stream LLM response           │
    │  2. Parse for tool calls (text)   │
    │  3. If tool calls:                │
    │     a. Execute each tool          │
    │     b. Feed results as user msg   │
    │     c. Continue to next iteration │
    │  4. If no tool calls:             │
    │     → Final answer, done          │
    └───────────────────────────────────┘
```

**Key design decision: text-based tool calling.**

vLLM's hermes parser does not reliably produce structured `tool_calls` for Qwen2.5-Coder. Instead:
- The system prompt describes available tools and their JSON format
- The model outputs tool calls as bare JSON text
- `tool_parser.py` extracts tool calls using bracket-matching (not regex)
- Tool results are fed back as `role: "user"` messages (not `role: "tool"`)
- This bypasses vLLM's OpenAI tool_call validation entirely

### 3.2 Tool Call Parser

The parser (`src/tool_parser.py`) handles multiple formats:

| Format | Example | Detection |
|---|---|---|
| Bare JSON | `{"name": "search_code", "arguments": {"query": "auth"}}` | Bracket matching for objects with "name" key |
| XML tags | `<tool_call>{"name": "..."}</tool_call>` | Regex extraction + JSON parse |
| Markdown | ` ```json {"name": "..."} ``` ` | Fence stripping + JSON parse |
| Structured | OpenAI `tool_calls` array | Direct dict access |

The `_find_json_objects()` function uses recursive bracket matching to correctly handle nested JSON braces, which simple regex patterns cannot do.

### 3.3 Context Builder

Manages token budget allocation across message components:

```python
BUDGET_32K = {
    "system_prompt": 1500,
    "repo_structure": 1000,
    "conversation": 4000,
    "tool_results": 17000,
    "response_margin": 9268,
}
```

When the conversation grows beyond budget, oldest non-system messages are trimmed automatically.

### 3.4 System Prompt Strategy

The system prompt enforces:
1. **Tool-first behavior**: The model MUST call at least one tool before answering
2. **Efficiency**: Maximum 4 tool calls per question
3. **Evidence-based**: Answers must cite file paths and line numbers from tool results
4. **Language matching**: Respond in the user's language

---

## 4. Index Subsystem

### 4.1 Indexing Pipeline

```
File Discovery (filter by extension, exclude dirs)
    │
    ▼
SHA256 Hash Check (incremental: skip unchanged files)
    │
    ▼
tree-sitter AST Parse
    │  Extracts: functions, classes, methods
    │  Metadata: name, kind, line range, docstring, calls
    ▼
Chunk Creation (one chunk per AST symbol)
    │
    ▼
BGE-m3 Embedding (CPU, batch_size=16)
    │
    ▼
ChromaDB Storage (cosine similarity, persistent)
    │
    ▼
Symbol Table (for find_references)
```

### 4.2 AST Parser

Uses tree-sitter with Python grammar. For each file:
- Walks the AST tree depth-first
- Extracts `function_definition` and `class_definition` nodes
- For class methods, builds qualified names (e.g., `ClassName.method_name`)
- Extracts docstrings from first expression statement in body
- Heuristically extracts call expressions for dependency tracking

Fallback: if tree-sitter is unavailable, falls back to line-based chunking (50 lines per chunk) and regex-based symbol extraction.

### 4.3 Retrieval Pipeline

```
search_code("authentication")
    │
    ▼
BGE-m3 query embedding (CPU)
    │
    ▼
ChromaDB cosine similarity search → top-20 candidates
    │
    ▼
bge-reranker-v2-m3 cross-encoder (GPU)
    │  Score: [query, document] pairs
    │  Normalize: sigmoid
    ▼
Sort by score, return top-15
```

**Why reranker on GPU**: Cross-encoder reranking of 20 candidates requires 20 forward passes. On CPU: 4-7 seconds. On GPU: <0.5 seconds. Since `search_code` is on the Agent's critical path (called 2-3 times per query), CPU reranking would add 8-21 seconds of pure reranker latency.

### 4.4 Incremental Indexing

Each file's SHA256 hash is stored in a cache (`.raa/index/hash_cache.json`). On re-index:
- Changed files: re-parse, re-embed, update ChromaDB
- Unchanged files: skipped (counted in `files_skipped`)
- Deleted files: chunks removed from ChromaDB

---

## 5. Tools

### 5.1 Tool Registry

All tools implement an async handler pattern:

```python
async def handler(**kwargs) -> str:
    # tool logic
    return result_string
```

The registry provides:
- `get_definitions()`: Returns OpenAI-compatible tool schemas for the LLM
- `execute(name, arguments)`: Dispatches tool calls with error handling
- Tool parameter aliases: `path`/`file_path`/`filepath` all accepted

### 5.2 Tool Catalog

| Tool | Description | Key Parameters |
|---|---|---|
| `search_code` | Semantic search with reranking | `query`, `top_k` (default 15) |
| `grep_code` | Exact text/regex via ripgrep | `pattern`, `file_pattern` |
| `read_file` | Read file contents with line numbers | `path`/`file_path`, `start_line`, `end_line` |
| `list_directory` | List directory contents | `path` (default ".") |
| `get_symbols` | AST symbol extraction | `path`/`file_path` |
| `find_references` | Heuristic symbol reference search | `name`/`symbol`/`query` |
| `run_tests` | Run pytest (disabled by default) | `args` |

### 5.3 Security: run_tests

`run_tests` is disabled by default (`security.run_tests_enabled: false`). Running pytest on an untrusted repository is equivalent to arbitrary code execution, because pytest imports `conftest.py` and test modules during the collection phase — before any test actually runs.

---

## 6. API Specification

### 6.1 Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/chat` | Agent chat (SSE streaming) |
| POST | `/api/index` | Trigger repository indexing |
| GET | `/api/index/status` | Indexing status |
| GET | `/api/health` | System health check |
| GET | `/api/workspace/tree` | Directory listing |
| GET | `/api/workspace/file` | File contents |
| GET | `/api/sessions` | List recent sessions |
| GET | `/api/sessions/{id}` | Session detail |
| DELETE | `/api/sessions/{id}` | Delete session |

### 6.2 Chat SSE Events

The `/api/chat` endpoint returns Server-Sent Events with the following event types:

| Event Type | Description | Fields |
|---|---|---|
| `text_delta` | Streaming token from LLM | `content`, `iteration` |
| `thinking` | Agent reasoning text (pre-tool) | `content`, `iteration` |
| `progress` | Human-readable tool progress | `content`, `tool`, `iteration` |
| `tool_call` | Tool being called | `content` (tool name), `arguments`, `iteration` |
| `tool_result` | Tool execution result | `content`, `tool`, `iteration` |
| `text` | Final answer (complete) | `content` |
| `done` | Session complete | `content` |
| `error` | Error occurred | `content` |

Example SSE stream:
```
data: {"type": "text_delta", "content": "Let me", "iteration": 1}
data: {"type": "text_delta", "content": " search", "iteration": 1}
data: {"type": "thinking", "content": "...", "iteration": 1}
data: {"type": "progress", "content": "Searching codebase for: AgentEngine", "tool": "search_code"}
data: {"type": "tool_call", "content": "search_code", "arguments": {"query": "AgentEngine"}}
data: {"type": "tool_result", "content": "Found 15 results...", "tool": "search_code"}
data: {"type": "text_delta", "content": "Based on", "iteration": 2}
data: {"type": "text", "content": "Based on the code..."}
data: {"type": "done", "content": "Based on the code..."}
```

---

## 7. AMD GPU Optimization

### 7.1 Hardware Context

| Spec | Value |
|---|---|
| GPU | AMD Radeon PRO W7900 |
| Architecture | RDNA3 (gfx1100) |
| VRAM | 48GB GDDR6 |
| Memory Bandwidth | 864 GB/s |
| FP16 TFLOPS (theoretical) | ~45 |

### 7.2 Throughput Analysis

**Decode-phase bandwidth ceiling:**

```
Theoretical max tokens/s = Memory Bandwidth / Model Size
                          = 864 GB/s / 28 GB (14B FP16)
                          ≈ 31 tok/s
```

This is the physical ceiling assuming 100% bandwidth utilization, zero overhead. Real-world factors reduce this:

| Factor | Impact |
|---|---|
| RDNA3 kernel efficiency vs CDNA | GEMM TFLOP utilization ~50% of CDNA |
| `enforce_eager` (no HIP graph) | -10 to -20% throughput |
| AOTriton attention backend | Varies by kernel |
| vLLM framework overhead | ~5-10% |

**Measured results:**

| Metric | Value | % of Theoretical |
|---|---|---|
| Single-request throughput | ~8 tok/s | 27% |
| 4-way concurrent | ~27 tok/s | — |
| 8-way concurrent | ~57 tok/s | — |
| TTFT (time to first token) | 0.26s | — |

### 7.3 enforce_eager

gfx1100 HIP graph capture frequently crashes or produces incorrect output. `--enforce-eager` skips graph capture entirely. This costs 10-20% throughput but provides reliable inference. Controlled via environment variable in `start_llm.sh`:

```bash
ENFORCE_EAGER=true   # default, stable
ENFORCE_EAGER=false  # try only after verifying graph mode stability
```

### 7.4 FP8 Status

FP8 is unavailable on gfx1100 for both weight quantization and KV cache:

- `--quantization fp8`: vLLM ROCm FP8 kernels target gfx942 (MI300X) Matrix Core. gfx1100 RDNA3 WMMA does not have equivalent FP8 compute path.
- `--kv-cache-dtype fp8`: Same kernel dependency. Most likely outcome: vLLM rejects startup with "FP8 KV cache not supported on this backend."

Benchmark narrative focuses on "FP16 + retrieval strategy" — using reranked semantic search to achieve effective results within the 32K context window, rather than relying on FP8 to extend context.

### 7.5 ROCm Stability Environment Variables

```bash
export PYTORCH_ROCM_ARCH=gfx1100     # compile target
export HSA_ENABLE_SDMA=0             # RDNA3 SDMA transfer fix
export AMD_SERIALIZE_KERNEL=3        # kernel race condition fix
export AMD_SERIALIZE_COPY=3          # copy race condition fix
```

These address known gfx1100 stability issues. Without them, GPU inference may produce NaN or inconsistent results across runs.

### 7.6 flash-attn Removal

The Docker image ships with a CUDA-compiled `flash-attn` package. On ROCm, it fails with `ModuleNotFoundError: No module named 'flash_attn_2_cuda'`. This must be uninstalled before vLLM can start:

```bash
pip uninstall flash-attn -y
```

`setup.sh` handles this automatically.

### 7.7 GPU Memory Budget

```
Process 1: vLLM (gpu_memory_utilization=0.88)
  ├── Model weights (14B FP16):     28 GB
  ├── PyTorch runtime:               2 GB
  └── KV cache pool (remaining):    12 GB
      Supports: ~2 concurrent 32K sequences
      Or:        ~4 concurrent 16K sequences
  Total:                           ~42 GB

Process 2: Reranker (separate process)
  ├── Model (bge-reranker-v2-m3):  0.6 GB
  └── HIP context + allocator:     0.9 GB
  Total:                           ~1.5 GB

Grand total: ~43.7 GB / 48 GB (91%)
Remaining:   ~4.3 GB
```

### 7.8 KV Cache Calculation

Qwen2.5-Coder-14B: 48 layers, 8 KV heads (GQA), head_dim=128

```
Per-token KV cache (FP16):
  2 (K+V) × 48 layers × 8 heads × 128 dim × 2 bytes = 196,608 bytes ≈ 192 KB/token

Single sequence 32K (FP16): 192KB × 32768 ≈ 6.0 GB
```

---

## 8. Security Model

### 8.1 Network Isolation

- API binds to `127.0.0.1` by default (loopback only)
- No inbound connections from external machines
- No outbound connections to any external service
- Verifiable: `tcpdump` shows zero traffic during operation

### 8.2 File Access Control

- Agent tools can only read files within the configured repository root
- Path traversal prevention: resolved paths must start with repo root
- Sensitive file patterns excluded from indexing: `*.env`, `*.key`, `*.pem`, `credentials*`, `secrets*`

### 8.3 Command Execution

- `run_tests` disabled by default
- Even when enabled, only runs configured test commands (`pytest`, `python -m pytest`)
- Timeout enforced (default 60s)

### 8.4 Read-Only Operations

The Agent cannot modify files. All tools are read-only except `run_tests`.

---

## 9. Session Management

Sessions persist as individual JSON files in `.raa/sessions/`. Each session stores:
- Session ID (timestamp-based)
- Creation timestamp
- Message history (role + content + timestamp)
- Auto-generated title (from first user message)

The session manager supports:
- Creating new sessions
- Adding messages
- Listing recent sessions (default: 10)
- Loading full conversation history
- Deleting sessions

---

## 10. Evaluation

### 10.1 Test Suite

20 questions across 5 categories:
- Understanding (5 questions): architecture, config, component behavior
- Bug localization (5 questions): security checks, fallback behavior, edge cases
- Cross-file analysis (5 questions): request flow tracing, dependency mapping
- Architecture (3 questions): design rationale, budget system, privacy
- Testing (2 questions): validation strategies

### 10.2 Scoring

LLM-as-judge evaluates each answer on a 0-3 scale:
- 3: Correct and complete, references specific files/lines
- 2: Mostly correct, minor gaps
- 1: Partially relevant, missing key info
- 0: Wrong or irrelevant

Target: >70% of questions scored >= 2.

---

## 11. Configuration Reference

```yaml
server:
  host: "127.0.0.1"            # loopback only (privacy)
  port: 8080

llm:
  backend: "vllm"
  model: "./models/Qwen2.5-Coder-14B-Instruct"
  base_url: "http://127.0.0.1:8000/v1"
  dtype: "float16"
  max_model_len: 32768
  gpu_memory_utilization: 0.88
  enforce_eager: true
  temperature: 0.3
  top_p: 0.9

embedding:
  model: "./models/bge-m3"
  device: "cpu"
  batch_size: 16

reranker:
  model: "./models/bge-reranker-v2-m3"
  device: "cuda"
  candidate_count: 20
  final_count: 15

agent:
  max_iterations: 8
  context_budget: 32768
  temperature: 0.3

security:
  run_tests_enabled: false
```

---

## 12. Deployment

### 12.1 Docker

```dockerfile
FROM vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0
# App deps installed into existing /opt/venv
# flash-attn removed automatically
# ROCm env vars baked in
```

### 12.2 Entry Modes

| Mode | Command | Description |
|---|---|---|
| `all` | `docker run ... raa` | Start vLLM + RAA together |
| `vllm` | `docker run ... raa vllm` | Only vLLM server |
| `app` | `docker run ... raa app` | Only RAA (vLLM must be separate) |
| `shell` | `docker run ... raa shell` | Bash for debugging |

---

## 13. Testing

```bash
# Unit tests (25 tests)
python -m pytest tests/ -v

# Environment verification
python scripts/verify_rocm.py

# Benchmark
python scripts/benchmark.py --base-url http://127.0.0.1:8000/v1

# Quality evaluation
python scripts/eval_agent.py --app-url http://127.0.0.1:8080
```

Test coverage:
- `test_tool_parser.py`: Structured + text format tool call parsing (10 tests)
- `test_parser.py`: tree-sitter AST chunk extraction (9 tests)
- `test_config.py`: Config loading, YAML parsing, ROCm env (6 tests)

---

## 14. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10 |
| Web Framework | FastAPI + Uvicorn |
| LLM Serving | vLLM 0.16.0 (ROCm 7.2.1) |
| LLM Model | Qwen2.5-Coder-14B-Instruct (FP16) |
| AST Parsing | tree-sitter + tree-sitter-python |
| Embedding | BAAI/bge-m3 (sentence-transformers / FlagEmbedding) |
| Reranker | BAAI/bge-reranker-v2-m3 (FlagEmbedding) |
| Vector Store | ChromaDB (cosine similarity) |
| Search | ripgrep (grep_code tool) |
| Frontend | Vanilla HTML/CSS/JS + highlight.js |
| Session Storage | JSON files |
| GPU | AMD Radeon PRO W7900 (ROCm 7.2.1) |
