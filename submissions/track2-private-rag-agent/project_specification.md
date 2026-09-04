# Project Specification — Private RAG Agent

**A Fully Offline, Local Private Multi-Agent RAG Assistant Optimized for AMD Radeon GPUs**

| Field | Value |
|---|---|
| Competition | 2026 AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents |
| Track Focus | Local deployment of agentic private AI; 40% of score from AMD Radeon GPU / ROCm optimization |
| Project Name | Private RAG Agent (`private-rag-agent`) |
| Core Principle | Data never leaves the machine. Chunking, embedding, retrieval, reasoning and verification all run locally. No cloud API dependency at runtime. |
| Team | MENG Yuxuan |
| Demo Video | [demo_video.md](../submissions/track2-private-rag-agent/demo_video.md) — Bilibili / YouTube (recording) |
| Submission Deadline | 2026-08-06 23:59 (UTC+8) |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Application Scenarios](#2-application-scenarios)
3. [System Architecture](#3-system-architecture)
4. [Core Capabilities](#4-core-capabilities)
5. [Model Stack & Local Deployment Plan](#5-model-stack--local-deployment-plan)
6. [AMD Radeon GPU / ROCm Optimization](#6-amd-radeon-gpu--rocm-optimization)
7. [Rigorousness and Trustworthiness](#7-rigorousness-and-trustworthiness)
8. [Performance Benchmark Plan](#8-performance-benchmark-plan)
9. [Repository Structure](#9-repository-structure)
10. [Roadmap](#10-roadmap)

---

## 1. Executive Summary

Private RAG Agent is an all-offline, locally deployed multi-agent Retrieval-Augmented
Generation (RAG) system. Given a complex question, it decomposes the question into
independent sub-questions, dispatches parallel research agents that retrieve from a
private knowledge base and write sub-reports, verifies every factual statement against
the retrieved source text, and finally composes a single answer using **only** the content
that passed verification. Every sentence of the final answer is auditable: each citation
links back to the exact source passage, and each sentence is labeled supported, partially
supported, or unsupported with a quantitative grounding score.

The system is architected around AMD Radeon GPUs and the ROCm software stack from day
one. It supports three interchangeable inference backends (Ollama/ROCm, llama.cpp/HIP,
vLLM/ROCm), runs quantized GGUF models with full-layer GPU offload, and exploits a
researcher-pool parallelism strategy to saturate GPU throughput — the key lever behind the
5–10x wall-clock speedup projected versus CPU inference.

---

## 2. Application Scenarios

The design targets organizations and individuals who cannot or will not send their data
to third-party clouds. Representative scenarios:

### 2.1 Private / Proprietary Knowledge Bases
Companies maintain confidential documentation — product technical manuals, internal
white papers, compliance rules, project planning documents. The assistant indexes these
documents locally and answers questions grounded strictly in the ingested corpus, with
citations that can be traced back to the original text. All parsing, embedding, retrieval,
generation and verification are executed on-premises; no document content is ever
transmitted to an external service.

### 2.2 Offline / Air-Gapped Environments
Defense, energy and industrial-control sites frequently operate on isolated networks with
no internet access. Because every component — model weights, vector store, reranker,
and LLM — is local, the system runs with the network cable disconnected. The only
prerequisite is a machine with sufficient CPU/GPU resources.

### 2.3 Enterprises with Data-Privacy and Compliance Requirements
GDPR, HIPAA, PIPL and other regimes impose strict controls on personal and sensitive
data. This system provides a deterministic answer pipeline where the provenance of each
statement is machine-checkable, which supports compliance audits ("which source supports
this claim?") in a way that closed-box cloud assistants cannot.

### 2.4 Local AI Assistants on AMD Workstations
For individual engineers and analysts, the system runs as a single-machine assistant on
an AMD Radeon workstation (recommended 16GB+ VRAM, e.g. Radeon RX 7900 XTX / W7900).
A single browser UI provides document ingestion, hybrid search, GPU monitoring, and a
fully transparent reasoning trail, with no per-token cloud billing.

---

## 3. System Architecture

### 3.1 End-to-End Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                                         │
│  UI (FastAPI + SSE streaming + native HTML/CSS/JS)                          │
│  ├── Streaming conversation (typewriter effect + live activity timeline)   │
│  ├── Execution trace panel (real-time tool / verification events)           │
│  ├── GPU monitoring panel (utilization / VRAM / temperature / clocks)       │
│  └── Source deep-dive drawer (click citation → original text + query hl)    │
├────────────────────────────────────────────────────────────────────────────┤
│  AGENT LAYER                                                                │
│  ├── Agent main loop   perceive → plan → tools → answer → citation check   │
│  ├── MultiAgent        decompose → parallel research → fact-check → synth   │
│  ├── Planner          task planning (auto-triggered on complex questions)   │
│  ├── Memory           multi-turn short-term + persistent long-term memory   │
│  └── Tools            rag_search / read_doc / list_docs / summarize / …     │
├────────────────────────────────────────────────────────────────────────────┤
│  RAG PIPELINE (hybrid retrieval + rerank)                                   │
│  ├── parser.py        PDF / Word / Markdown / Excel / PPT parsing           │
│  ├── chunk_text       smart chunking (512 chars, 64 overlap)                │
│  ├── query rewriting  LLM generates synonym / precision retrieval variants  │
│  ├── vector search    ChromaDB (bge-m3, cosine)                             │
│  ├── BM25             keyword exact recall (proper nouns / acronyms)        │
│  ├── RRF fusion       Reciprocal Rank Fusion                                │
│  └── cross-encoder    bge-reranker-v2-m3 rerank (top-k precision)           │
├────────────────────────────────────────────────────────────────────────────┤
│  VERIFICATION LAYER                                                         │
│  ├── groundedness     sentence-vs-source 3-gram overlap score               │
│  ├── citation         cited filenames must exist in the knowledge base      │
│  └── LLM-as-judge     per-claim support determination (multi-agent mode)    │
├────────────────────────────────────────────────────────────────────────────┤
│  INFERENCE BACKENDS (llm.py, unified chat interface)                        │
│  ├── ollama / llama.cpp (GGUF + ROCm)                                      │
│  └── vLLM (ROCm — Radeon Cloud, high concurrency)                           │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Multi-Agent Collaboration Pipeline

```
                          user question
                                │
                                ▼
                ① Decomposer ── splits into n independent sub-questions
                   (LLM, JSON array output, temperature 0.1)
                                │
                                ▼
                ② Researchers ── n parallel sub-agents
                   each: RAG retrieval + sub-report generation
                   (tool/verification events streamed live to UI)
                                │
                                ▼
                ③ Fact-Checker ── two-tier verification per sub-report
                   · groundedness: sentence vs retrieved source 3-gram overlap
                   · LLM-as-judge: per-claim support determination
                                │
                                ▼
                ④ Synthesizer ── composes the final answer using ONLY
                   content that passed verification
                   ([来源:doc] citation format enforced)
                                │
                                ▼
                ⑤ Final check ── re-runs groundedness + citation
                   verification on the synthesized answer
```

**Parallelism rationale (AMD-specific).** On a local GPU, multiple inference requests
queue for the same device. Serially executing a multi-step research task multiplies
wall-clock latency; running the `n` researchers concurrently cuts the wall-clock time of
multi-step research tasks substantially. Meanwhile the `n` sub-agents share a single copy
of the embedding and reranker models (module-level singletons), so VRAM overhead grows
by only one copy, not `n`.

### 3.3 Component Responsibilities

| Component | Responsibility |
|---|---|
| `agent/agent.py` | Single-agent main loop: intent gating, planning, streaming tool execution, citation verification |
| `agent/multi_agent.py` | Orchestration: decompose → parallel research → fact-check → synthesize, with a rich SSE event stream |
| `agent/rag.py` | Hybrid retrieval: query rewrite + vector ∪ BM25 → RRF → cross-encoder rerank |
| `agent/verify.py` | Deterministic groundedness (n-gram) and citation-existence verification |
| `agent/llm.py` | Unified inference backend abstraction (ollama / llama_cpp / vLLM-openai-compat) |
| `agent/parser.py` | Multi-format document parsing and smart chunking |
| `agent/planner.py` | Task planning; `agent/memory.py` short- and long-term memory |
| `ui/server.py` | FastAPI + SSE backend; document ingest; session management; GPU telemetry |
| `benchmarks/bench_amd.py` | Automatic AMD/ROCm detection and tokens/s benchmark harness |

---

## 4. Core Capabilities

### 4.1 Offline Multi-Agent RAG
A full Decomposer → parallel Researchers → Fact-Checker → Synthesizer pipeline runs
entirely offline. Complex questions are decomposed into independent sub-questions;
researchers execute in parallel; a fact-checker verifies each sub-report; and the
synthesizer produces a single integrated answer that cites sources in `[来源:doc]` format.

### 4.2 Hybrid Retrieval with Reranking
Two retrieval signals are fused for recall and precision:

1. **Query rewriting** — a lightweight LLM call rewrites the query into up to 3 retrieval
   variants (retaining intent, completing proper nouns/acronyms), improving recall on
   paraphrase-heavy questions.
2. **Vector search** — ChromaDB with `bge-m3` embeddings (1024-dim, cosine distance),
   tuned for multilingual and Chinese content.
3. **BM25 keyword search** — exact-keyword recall that complements semantic search on
   proper nouns, abbreviations, and version identifiers (e.g. "Q4_K_M", "ROCm 6.x").
4. **Reciprocal Rank Fusion (RRF)** — rank-based fusion (k=60) of both result lists, with
   a configurable BM25 weight (default 0.4) that is robust to score-calibration mismatch.
5. **Cross-encoder rerank** — `BAAI/bge-reranker-v2-m3` jointly scores (query, passage)
   pairs and reorders the fused candidate pool (default 16 → top 4). Cross-encoder
   relevance is markedly more accurate than bi-encoder distance and is the single
   highest-leverage point for RAG precision.
6. **Near-duplicate dedup** — chunks >95% character-identical are dropped before
   reranking so redundant context never reaches the model.
7. **Adaptive candidate pool** — weakly-scored filler below `max(0.5 × top_score, 0.15)`
   is trimmed after reranking, so the answer is grounded only in genuinely relevant
   evidence rather than diluted by padding.
8. **Contextual compression** — each returned chunk is reduced to its query-relevant
   sentences (deterministic character 3-gram overlap against the query), giving the LLM
   tighter, more focused context at lower token cost. A retrieval **confidence** signal
   (0–1) is attached to every search result for downstream honesty checks.

The entire pipeline is local and offline; every stage degrades gracefully (pure vector
search is the guaranteed fallback).

### 4.3 Verifiable, Citable Answers
Every answer sentence is checked against the retrieved source text (see Section 7).
Citations are enforced to reference only documents that actually exist in the knowledge
base. The UI exposes a per-sentence verification panel and a composite trust score.

### 4.4 Per-Sentence Groundedness Panel
The UI renders each answer sentence with its support level — **supported / partial /
unsupported** — and its grounding score. Unsupported content is surfaced honestly to the
user rather than silently presented as fact.

### 4.5 Multi-Format Document Import
Documents are parsed from PDF, Word (.docx), Markdown, Excel (.xlsx), CSV, JSON, PPT
(.pptx) and plain text, chunked at 512 characters with a 64-character overlap, embedded,
and stored in ChromaDB. Ingestion is idempotent (content-hash based); documents can be
added and listed through the web UI or CLI (`python main.py ingest`), and removed through
the web UI.

### 4.6 Live GPU Monitoring
A dedicated panel polls GPU utilization, VRAM usage, temperature, power draw and core
clocks via `pyamdgpuinfo` or `rocm-smi --json` (with a demo-data fallback on non-AMD
development machines), letting the user watch the parallelism and quantization strategy
in action during inference.

### 4.7 Memory and Planning Tools
The agent supports multi-turn short-term memory (configurable, default last 10 turns)
and persistent long-term memory, native function-calling tools (`rag_search`, `read_doc`,
`list_docs`, `summarize`, `web_search_offline`), and a planner that auto-triggers on
complex questions (compare/analyze/plan keywords) to keep single-shot answers fast.

---

## 5. Model Stack & Local Deployment Plan

### 5.1 Model Selection

| Role | Model | Size / Type | Rationale |
|---|---|---|---|
| LLM | **Qwen3-8B** (`qwen3:8b`) | 8B decoder-only | Strong function calling, multilingual (incl. Chinese), fits 16GB-class Radeon GPUs when quantized |
| Embedding | **BAAI/bge-m3** | 1024-dim multilingual embedding | High-quality Chinese/English retrieval; used for both ingestion and query encoding |
| Reranker | **BAAI/bge-reranker-v2-m3** | cross-encoder (512 tokens) | Multilingual cross-encoder; substantially improves top-k precision over bi-encoder scores |

The stack is deliberately small-model focused: a quantized 8B-class LLM, a 1024-dim
embedding model, and a compact cross-encoder together fit comfortably in the 16–24GB
VRAM class of AMD workstation GPUs, keeping cost and power low while retaining strong
reasoning and retrieval quality.

### 5.2 Inference Backends

The `LLMBackend` abstraction exposes one `chat` / `chat_stream` / `embed` interface
regardless of backend; a single `config.yaml` switch selects the runtime.

| Backend | Runtime stack | Target environment |
|---|---|---|
| **Ollama** | Ollama with automatic ROCm device backend on Linux (`ollama ps` confirms 100% GPU) | Simplest local setup; Windows/macOS/Linux development |
| **llama.cpp (HIP)** | GGUF + `CMAKE_ARGS="-DGGML_HIP=ON"`, `n_gpu_layers=-1` full GPU offload | Single-machine, single-GPU, maximum control over quantization |
| **vLLM (ROCm)** | `rocm/vllm` container; OpenAI-compatible API; high concurrency | Radeon Cloud and multi-tenant/high-concurrency GPU environments |

### 5.3 Quantization

GGUF quantization balances VRAM footprint against speed and quality. Both variants are
fully GPU-offloaded:

| Quantization | Approx. VRAM | Speed | Recommendation |
|---|---|---|---|
| `Q8_0` | ~8.2 GB | Fast | Quality-first deployments |
| **`Q4_K_M`** | ~4.6 GB | Fastest | **Balanced default recommendation** |

`Q4_K_M` is the recommended default: it fits comfortably alongside the embedding and
reranker models within 16GB VRAM, leaving headroom for long context and concurrent
researcher requests.

### 5.4 Deployment Paths

**Path A — Local (pip + Ollama).** Install Python 3.10+, pull `qwen3:8b` and `bge-m3`
into Ollama, `pip install -r requirements.txt`, then:

```bash
python main.py ingest data/docs/   # batch-import documents
python main.py ui                  # http://localhost:7860
```

**Path B — Docker Compose.** The repository ships a `docker-compose.yml` running the
application plus an Ollama container. On AMD + ROCm hosts, uncommenting the `devices`
section in the compose file passes the GPU into the container:

```bash
docker compose up -d --build
docker exec -it private-rag-ollama ollama pull qwen3:8b
docker exec -it private-rag-ollama ollama pull bge-m3
```

**Path C — AMD Radeon Cloud (`deploy_rc.sh`).** A one-shot script for Radeon Cloud
(Jupyter workspace, ROCm + PyTorch preinstalled): detects the AMD GPU via
`amd-smi`/`rocm-smi`; starts a vLLM (ROCm) inference server (auto-detecting RC-preloaded
models such as `Qwen3.6-35B-A3B-AWQ-4bit`, else `Qwen/Qwen3-8B`); installs dependencies;
switches `config.yaml` to the vLLM backend with `sentence-transformers` embeddings
(keeping `bge-m3` at 1024-dim for vector-database compatibility); and runs an end-to-end
inference smoke test.

### 5.5 Hardware Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| GPU | AMD Radeon with ROCm support, 16GB VRAM | Radeon RX 7900 XTX / W7900 (or Radeon Cloud instance) |
| ROCm | ROCm 6.x (Linux) | ROCm 6.x + Ollama/llama.cpp ROCm build |
| RAM | 16 GB | 32 GB |
| Python | 3.10+ | 3.11 |

---

## 6. AMD Radeon GPU / ROCm Optimization

This section is the direct response to the Track 2 scoring emphasis (AMD Radeon GPU /
ROCm optimization, 40%).

### 6.1 Native ROCm Inference Backend
The default inference stack is ROCm-native: llama.cpp compiled with `GGML_HIP=ON`, or
Ollama's ROCm backend, or vLLM on ROCm wheels for Radeon Cloud. No CUDA-specific path is
required, and model weights run fully on the Radeon GPU (`n_gpu_layers=-1`, `ollama ps`
shows 100% GPU residency).

### 6.2 GGUF Quantization
Quantization reduces both VRAM footprint and memory bandwidth per token. `Q4_K_M`
(~4.6GB) is the recommended operating point for an 8B model on 16GB GPUs, with `Q8_0`
(~8.2GB) available when maximum precision is needed. Because Radeon VRAM bandwidth is
the dominant throughput constraint for LLM decode, smaller quantizations translate almost
directly into higher tokens/s.

### 6.3 Module-Level Model Singletons (VRAM Budget)
Embedding and cross-encoder reranker models are loaded as **module-level singletons** and
shared across all agents and RAGStore instances. In multi-agent mode, `n` researchers
therefore add only inference concurrency, not `n` extra copies of the embedding and
reranker in VRAM. Models are also lazily loaded on first use, so the service does not
pre-allocate VRAM at startup.

### 6.4 Multi-Agent Parallelism to Saturate the GPU
The orchestrator runs `n` researcher agents concurrently via a thread pool. On a single
local GPU, concurrent decode requests are interleaved to keep compute units busy; this
turns the "serialized multi-step research" latency into the latency of the slowest single
sub-task. The wall-clock gain grows with sub-question count, and the shared model
singletons ensure the gain is not paid for in VRAM.

### 6.5 Cross-Encoder Rerank on GPU
Reranking runs the cross-encoder through the same ROCm path, keeping rerank latency to
millisecond scale while adding the precision that dominates final answer quality.

### 6.6 Concurrency Safety on Native Libraries (Engineering Note)
ChromaDB's underlying hnswlib and PyTorch's cross-encoder are not thread-safe under
concurrent `collection.query` / `collection.get` / reranker inference, which can produce
intermittent segfaults (exit code 139) under multi-agent retrieval. All paths touching
these native resources — `search()`, corpus loading, document add/remove — are therefore
serialized through a **process-level reentrant lock** (`threading.RLock`). The RLock is
required because `search()` internally re-enters corpus loading; LLM inference (the
dominant cost) remains naturally concurrent through the Ollama/vLLM service, so the lock
adds only milliseconds of serialization while eliminating the crash class.

### 6.7 Verification and Monitoring Tooling
```bash
rocminfo                  # confirm ROCm device presence
rocm-smi                  # live GPU memory / temperature / utilization
ollama ps                 # confirm model is 100% GPU-resident
python benchmarks/bench_amd.py   # auto-detect and output tokens/s
```

---

## 7. Rigorousness and Trustworthiness

**The innovation highlight of this project.** LLM hallucination is the central trust
problem for private assistants. This system makes each claim machine-auditable through a
three-layer verification stack, all local and mostly deterministic.

### 7.1 Groundedness Verification (Deterministic)
For every sentence of an answer, the verifier computes character-level **3-gram overlap**
between the normalized sentence and the normalized retrieved source passages (stop-words
and punctuation removed; 3-gram is robust to light paraphrasing). Each sentence is
labeled:

- **supported** — overlap ratio > 0.30
- **partial** — overlap ratio > 0.12
- **unsupported** — otherwise

The overall grounding score is the mean support ratio across sentences. This is fully
deterministic (no LLM), fast, and explainable — the exact overlap that produced each label
can be displayed. Because sub-reports are verified against the **full document text** of
the actually retrieved sources (not truncated tool outputs), scores are accurate even when
the final answer is lightly rephrased.

### 7.2 Citation Verification
Answers are required to cite sources in `[来源:filename]` form. The verifier:
1. Parses citations from the answer via regex.
2. Cross-checks each cited filename against the set of documents actually retrieved in
   this session.
3. Reports **citation precision** (fraction of citations that exist in the knowledge
   base), and flags every invalid citation.

If the answer cites nothing, this is surfaced as "no sources cited" rather than silently
passed — the user always knows the provenance status.

### 7.3 LLM-as-Judge (Fact-Check in Multi-Agent Mode)
In multi-agent mode, a third stage runs an LLM judge against each sub-report: the judge
reads the sub-report plus its retrieved sources and emits a JSON array of per-claim
verdicts (`{claim, supported, reason}`). Claims judged unsupported are collected and
reported as flags (e.g., "verification found N unsupported claims: …"). This is a
best-effort stage — failures degrade gracefully without blocking the pipeline — but when
it runs it adds semantic judgment on top of the n-gram overlap.

### 7.4 Verify-Then-Synthesize (What the User Sees)
The synthesizer is instructed to compose the final answer **only from sub-reports that
passed verification**, to keep `[来源:doc]` citations to documents that truly exist, and to
explicitly state when part of a sub-report is only partially or not supported. After
synthesis, a **final check** re-runs groundedness and citation verification on the
complete answer. The UI then shows:

- a composite **trust score** (grounding + citation precision);
- a **per-sentence panel** with supported/partial/unsupported labels and scores;
- a **source deep-dive drawer** — clicking any citation opens the original passage with
  the query terms highlighted.

---

## 8. Performance Benchmark Plan

The repository ships `benchmarks/bench_amd.py`, which auto-detects the AMD/ROCm
environment (`rocminfo` / `rocm-smi`), warms the model, and measures tokens/s and
latency over repeat runs for a standard prompt set.

### 8.1 Baseline (Development Machine)

Measured on the development machine (NVIDIA RTX 4070 Laptop, Ollama `qwen3:8b`) with the
benchmark harness:

| Metric | Value |
|---|---|
| CPU inference throughput | ~1.8 tokens/s |

### 8.2 Expected Results on AMD Radeon GPU / ROCm

The table below reports the measured CPU baseline and the projected AMD targets. The
AMD rows will be updated with measured Radeon Cloud numbers once the benchmark notebook
(`tools/rc/rc_benchmark.ipynb`) is run on the cloud instance; the projection is **5–10x**
over the CPU baseline. A CPU measurement artifact is included in the repo.

| Config | Tokens/s | First-token latency | VRAM | Notes |
|---|---|---|---|---|
| CPU baseline (dev, qwen3:8b) | 0.2–11 (measured) | — | — | reference point; `benchmarks/results/bench_local_20260806.txt` |
| RX 7900 / ROCm, GGUF Q4_K_M, full offload | projected 5–10x | expected sub-second | ~4.6 GB | balanced default |
| RX 7900 / ROCm, GGUF Q8_0, full offload | projected 5–10x | expected sub-second | ~8.2 GB | quality mode |
| Radeon Cloud, vLLM | projected 5–10x | expected sub-second | — | high concurrency |

Command to reproduce:
```bash
python benchmarks/bench_amd.py --repeat 3
```

---

## 9. Repository Structure

```
private-rag-agent/
├── agent/
│   ├── agent.py        # Agent main loop (planning / tools / memory / citation check)
│   ├── multi_agent.py  # Multi-agent orchestration (decompose→research→check→synthesize)
│   ├── rag.py          # Hybrid retrieval (vector ∪ BM25 → RRF → rerank)
│   ├── verify.py       # Groundedness + citation verification
│   ├── llm.py          # Unified inference backends (ollama / llama.cpp / vLLM)
│   ├── parser.py       # Multi-format document parsing + smart chunking
│   ├── tools.py        # Tool registry (function calling)
│   ├── memory.py       # Short-term + long-term memory
│   └── planner.py      # Task planning
├── ui/
│   ├── server.py       # FastAPI + SSE streaming endpoints
│   └── static/         # Native HTML/CSS/JS professional dark UI
├── benchmarks/
│   └── bench_amd.py    # AMD ROCm benchmark harness
├── data/docs/          # Knowledge base (6 markdown documents, 15 chunks)
├── config.yaml         # Model / retrieval / chunking / quantization configuration
├── main.py             # Entry point (ingest / ask / ui)
├── deploy_rc.sh        # Radeon Cloud one-shot deployment script
├── docker-compose.yml  # Containerized deployment
├── docs/               # This specification + submission materials
└── requirements.txt
```

---

## 10. Roadmap

- **Final AMD benchmark pass** — fill Section 8.2 with measured RX 7900-class / Radeon
  Cloud numbers, including multi-agent parallel speedup curves.
- **Agent memory upgrades** — richer long-term memory consolidation and cross-session
  personalization.
- **Knowledge-base scale-out** — sharded vector collections for corpora beyond the
  single-host default.
- **Structured evaluation** — RAGAS-style faithfulness/answer-relevancy scores on a
  curated gold set, to complement the deterministic n-gram verification.
- **Multi-GPU (MIG-style) scheduling** for Radeon Cloud deployments with multiple
  accelerators.
