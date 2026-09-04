# Private RAG Agent — Presentation Slide Outline

**Deck target:** ~12 slides, supplementary submission material for AMD AI DevMaster 2026, Track 2 (Development & Local Deployment of Private AI Agents).
**Audience:** hackathon judges (engineering + AMD platform).
**Design language:** dark "precision instrument" theme; AMD red accent (#ED1C24) used only for key metrics, state borders, and highlight glows. Dense text, real metrics, no decorative filler.

---

## Slide 1 — Title

**Title:** Private RAG Agent — Fully Offline, Multi-Agent RAG on AMD Radeon
**Subtitle:** Track 2 · Development & Local Deployment of Private AI Agents · AMD AI DevMaster 2026

Bullets:
- A fully offline, local private multi-agent RAG assistant: ingest private documents, then decompose, research, fact-check, and synthesize answers without any cloud API.
- Data never leaves the machine: chunking, embedding, retrieval, and inference all run locally on AMD Radeon GPU / ROCm.
- Rethinks the "trust" problem: every sentence is grounded against the retrieved source text; every citation is verified against the knowledge base.
- Ships three inference backends (llama.cpp HIP, Ollama ROCm, vLLM) and deploys on bare metal, Docker, or AMD Radeon Cloud.

**Visual:** Full-bleed dark background, AMD red accent bar; project logo/wordmark top-left, Track 2 tag top-right.

---

## Slide 2 — Problem: Private Data Meets Cloud AI

**Title:** Private Data Must Not Cross the Network

Bullets:
- Enterprise and individual data (contracts, specs, internal docs) is precisely the content that cannot be sent to cloud LLM APIs — regulatory, confidentiality, and IP risk.
- Cloud RAG compounds the problem: even "hosted private" solutions imply third-party custody of the index and query logs.
- Local answers to complex questions need the same quality as cloud: multi-hop reasoning, retrieval over long documents, and verifiable citations.
- Gap: off-the-shelf local chatbots give single-turn retrieval with no grounding guarantees; serious local agentic RAG is rare.

**Visual:** Split panel — left: "cloud" (upload arrows to a server icon, red X); right: "local" (GPU card icon inside a machine boundary, check mark). One line at bottom: "Track 2 answers this with a locally deployed agent that is auditable by construction."

---

## Slide 3 — Solution Overview

**Title:** A Fully Offline Private Multi-Agent RAG Assistant

Bullets:
- Ingest PDF / Word / Markdown / Excel / PPT into a local knowledge base (6 docs, 15 chunks in the demo corpus).
- Answer complex questions through a four-stage agent pipeline: Decompose → Parallel Research → Fact-Check → Synthesize.
- Hybrid retrieval with cross-encoder reranking retrieves precise evidence, not just similar text.
- Two trust mechanisms (groundedness scoring + citation verification) make every answer auditable.
- Runs entirely on one machine — zero cloud dependencies, zero data egress.

**Visual:** One-line feature ribbon across the top (Offline / Multi-Agent / Trust-Verified / AMD ROCm). Center: small block diagram — [Private Docs] → [Local Knowledge Base] → [RAG Agent] → [Verified Answer]. Callout badge: "No cloud API. No data egress."

---

## Slide 4 — Agent Architecture

**Title:** Agent Architecture — One Loop, Four Layers

Bullets:
- Agent core loop: perceive → plan → act (tool calls) → answer → verify citations; planning automatically triggers the multi-agent pipeline on complex questions.
- Tools: `rag_search`, `read_doc`, `list_docs`, `summarize`, offline web search — registered and callable via native tool calling.
- Memory: multi-turn short-term history plus a long-term memory file across sessions.
- RAG layer: parser + smart chunking (512-char chunks, 64 overlap), hybrid retrieval, cross-encoder rerank.
- Inference: unified `LLMBackend` abstraction — Ollama / llama.cpp (HIP) / vLLM (OpenAI-compatible), swap via `config.yaml`.

**Visual (diagram):** Layered stack from bottom to top:
1. Inference backends — Ollama (ROCm) | llama.cpp (HIP/GGUF) | vLLM (ROCm)
2. Trust layer — groundedness + citation verification + LLM-as-judge
3. RAG pipeline — parse → chunk → hybrid retrieval → rerank
4. Agent layer — memory · planner · tools · main loop
5. UI — FastAPI + SSE + native HTML/CSS/JS
Arrows between layers; AMD red highlight on the ROCm backend row.

---

## Slide 5 — Multi-Agent Pipeline (The Parallelism Story)

**Title:** Decompose → Parallel Research → Fact-Check → Synthesize

Bullets:
- Decomposer splits the question into n independent sub-questions (JSON, temperature 0.1), no cross-dependencies so they can run in parallel.
- n Researcher sub-agents run concurrently via ThreadPoolExecutor; each retrieves the knowledge base and emits a sub-report with its own source set.
- Fact-Checker applies two-stage verification to every sub-report: deterministic groundedness (n-gram overlap vs. retrieved text) plus an LLM-as-judge pass over individual claims.
- Synthesizer composes the final answer exclusively from verified content; each section carries a `[来源:file]` citation.
- Final answer is re-verified end-to-end (groundedness + citation precision) before being shown.

**AMD parallelism motivation (callout box):**
- On a local GPU, inference requests queue; serializing n research steps multiplies wall-clock time. Parallelizing saturates GPU utilization and cuts multi-step wall-clock time substantially.
- n sub-agents share one embedding model and one reranker (module-level singletons), so parallelism costs only one copy of each model in VRAM.
- Retrieval-native calls are serialized with a process-level reentrant lock (ChromaDB/hnswlib and torch cross-encoder are not thread-safe), so concurrency is safe — fixes the segfault class (exit 139) seen in early prototypes.

**Visual:** Horizontal pipeline diagram — Q → [Decomposer] → (n parallel Researcher boxes with GPU utilization bars) → [Fact-Checker] → [Synthesizer] → Verified answer. Each sub-agent shows a mini GPU load ticker to convey parallel saturation.

---

## Slide 6 — Hybrid Retrieval + Rerank

**Title:** Retrieval That Finds Evidence, Not Just Similar Text

Bullets:
- Query rewriting: a light local LLM call produces up to 2 synonym / precision variants (filters out degenerate rewrites).
- Vector search: ChromaDB (hnswlib, cosine) with bge-m3 embeddings — semantic recall.
- BM25 keyword search with CJK-aware tokenization (2-gram sliding window for Chinese) — exact-match recall for proper nouns and abbreviations that pure vectors miss.
- Reciprocal Rank Fusion (RRF, weight vector 0.6 / BM25 0.4) merges both rankings.
- Cross-encoder rerank (`BAAI/bge-reranker-v2-m3`) scores (query, doc) pairs jointly — the single highest-value precision upgrade in RAG, reranking a 16-candidate pool to top-k.
- Every stage degrades gracefully: pure vector search is the fallback floor.

**Visual (table):** recall mechanism comparison.
| Mechanism | What it catches | Weakness |
|---|---|---|
| Vector (bge-m3, cosine) | Semantic paraphrase | Misses rare terms / acronyms |
| BM25 keyword | Proper nouns, IDs, exact phrases | No semantics |
| RRF fusion | Union of both, rank-stable | — |
| Cross-encoder rerank | Top-k precision on (Q,D) | Compute cost (small pool) |

**Visual (chart):** funnel — 16 hybrid candidates → rerank → top 4 (labeled "Top-k precision").

---

## Slide 7 — Trustworthiness (The Differentiator)

**Title:** Auditable Answers: Groundedness + Citation Verification

Bullets:
- Groundedness: each answer sentence is checked against the retrieved source text via character 3-gram overlap (normalized, punctuation-stripped) and labeled Supported / Partial / Unsupported with a 0–1 score.
- Citation verification: every `[来源:file]` reference in the answer must actually exist in the knowledge base — prevents fabricated sources.
- LLM-as-judge (multi-agent mode): a second model reviews each factual claim against the sources and flags unsupported statements.
- Synthesizer only uses sub-reports that pass verification; unverified sections are disclosed in the answer.
- UI renders a per-sentence verification panel with a trust score — the judge can see exactly which sentence rests on which evidence.

**Visual (mock UI snippet):** answer text with per-sentence colored tags — green "Supported", amber "Partial", red "Unsupported" — and a trust score gauge (e.g., grounding 0.92 / citation precision 1.0). Callout: "Deterministic checks — fast and stable, no extra LLM cost."

---

## Slide 8 — AMD / ROCm Optimization

**Title:** Multi-Backend, Quantized, VRAM-Slim — Built for Radeon

Bullets:
- Three inference backends selected per scenario: llama.cpp (HIP, GGUF full-GPU offload) for single machine; Ollama (ROCm) for out-of-the-box; vLLM (ROCm) for high concurrency and Radeon Cloud.
- GGUF quantization: Q4_K_M (~4.6 GB VRAM, fastest) is the recommended balance; Q8_0 (~8.2 GB) for precision.
- VRAM sharing: embedding and reranker models are module-level singletons — n parallel agents load one copy globally, so parallelism adds a single footprint.
- Lazy loading: retrieval/rerank models load on first use, not at startup — keeps startup VRAM low.
- Verification and monitoring: `rocminfo`, `rocm-smi`, `ollama ps` (confirms 100% GPU), and `benchmarks/bench_amd.py` (auto-detects GPU, reports tokens/s).

**Visual (table):** quantization trade-off.
| Quantization | VRAM | Speed | Recommended use |
|---|---|---|---|
| Q8_0 | ~8.2 GB | Fast | Precision-critical |
| **Q4_K_M** | **~4.6 GB** | **Fastest** | **Balanced default** |

**Visual (mini diagram):** "One copy per GPU" — three agent boxes all pointing to one shared embedding block + one shared reranker block, with a single VRAM budget bar.

---

## Slide 9 — Performance

**Title:** Baseline Recorded, Headroom Documented on AMD

Bullets:
- Baseline estimated on dev machine (NVIDIA RTX 4070 Laptop, Ollama qwen3:8b, CPU inference): ≈ 1.8 token/s.
- Radeon Cloud target (RX 7900, ROCm, GGUF Q4_K_M, full-layer GPU offload): projected 5–10x throughput.
- Benchmarks are automated and reproducible via `benchmarks/bench_amd.py`; final submission includes the AMD-measured table.
- Metrics tracked per phase: retrieval latency (ms), rerank latency (ms), generation throughput (tokens/s), multi-agent end-to-end wall clock.
- Concurrency benefit: multi-agent wall-clock time scales with n parallel researchers because GPU utilization is the bottleneck, not latency.

**Visual (table — fill with measured values before presenting):**
| Workload | CPU (baseline) | AMD ROCm / GPU (measured) | Speedup |
|---|---|---|---|
| LLM generation (tokens/s) | ~1.8 | __ | __ |
| Embedding batch (ms) | __ | __ | __ |
| Hybrid retrieval + rerank (ms) | __ | __ | __ |
| Multi-agent end-to-end (s) | __ | __ | __ |

Footnote: "Benchmarks produced with `benchmarks/bench_amd.py`; hardware: AMD RX 7900 XTX / ROCm 6.x, Q4_K_M."

---

## Slide 10 — Deployment

**Title:** One Codebase, Three Deployment Paths

Bullets:
- Local: `pip install -r requirements.txt` + Ollama (`ollama pull qwen3:8b`, `ollama pull bge-m3`); `python main.py ingest` then `python main.py ui`.
- Docker: `docker compose up -d --build` provisions the app and an Ollama service; uncommenting the `devices` block gives the GPU to the container on AMD + ROCm hosts.
- Radeon Cloud: `deploy_rc.sh` is a 6-step one-shot — detects the GPU, installs/verifies vLLM (ROCm wheels), picks up RC pre-downloaded models (e.g., Qwen3.6-35B-A3B-AWQ-4bit), rewrites `config.yaml` to the vLLM backend, and smoke-tests AMD inference.
- vLLM tuning on RC: `HIP_VISIBLE_DEVICES=0`, TRITON_ATTN backend, int8 KV-cache, `--gpu-memory-utilization 0.90`, auto-tool-choice for agentic calls.
- Backend swap is config-only (`model.backend: ollama | llama_cpp | vllm`) — no code changes between local and cloud.

**Visual:** Three-path diagram (Local / Docker / Radeon Cloud) converging on one codebase box. Environment variable overrides (`OLLAMA_HOST`) and `HIP_VISIBLE_DEVICES` noted as the only toggles.

---

## Slide 11 — Demo Highlights

**Title:** UI That Shows the Work, Not Just the Answer

Bullets:
- Streaming SSE chat with typewriter effect and a live activity timeline — every tool call and verification event from sub-agents appears in real time.
- GPU monitoring panel: utilization, VRAM, temperature, power, clock — pulled from `pyamdgpuinfo` / `rocm-smi` (demo data fallback when no AMD GPU is present).
- Source deep-dive drawer: click any citation to open the original document text with the query terms highlighted.
- Per-sentence verification panel with Supported / Partial / Unsupported tags and a trust score; multi-agent mode shows each sub-question, its grounding score, and the final synthesized answer.
- Three-column professional dark UI built with native HTML/CSS/JS + FastAPI (no heavy widget framework).

**Visual:** Three UI mockup screenshots — (1) activity timeline + GPU panel, (2) source drawer with highlighted query terms, (3) per-sentence verification tags + trust score gauge. Layout as a wide triptych with the live GPU panel top-right.

---

## Slide 12 — Closing

**Title:** Local, Parallel, Verifiable — Private RAG Done Right

Bullets:
- Fully offline multi-agent RAG: decompose → parallel research → fact-check → synthesize, no cloud dependency.
- Two independent trust mechanisms make answers auditable sentence by sentence.
- Purpose-built for AMD: multi-backend ROCm inference, quantization table, shared-model VRAM strategy, vLLM on Radeon Cloud.
- Reproducible benchmarks and one-shot Radeon Cloud deployment script included.
- Team: [team name] · Submission: video + this deck + repository (README covers architecture, optimization, and deployment).

**Visual:** Closing statement centered on dark background with a single AMD red rule; repository QR code and team credits bottom-left, Track 2 label bottom-right.

---

## Speaker Notes Summary (for the presenter)

- Slide 5 is the narrative core: the AMD-specific claim is "parallelism is free in VRAM" (shared singletons) and "parallelism wins because GPU utilization, not latency, is the bottleneck."
- Slide 7 is the differentiator: demo the per-sentence panel live — show an unsupported sentence being flagged and disclosed rather than hidden.
- Slides 8–9 are scored work (40% AMD/ROCm): keep the quantization table and the benchmark placeholder honest — say explicitly these are baseline + projected, measured table to be inserted.
- Slide 10: the Radeon Cloud deploy is a 6-step script — mention it runs end-to-end unattended.
