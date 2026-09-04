# Private RAG Agent — Track 2 Submission

**A fully offline, local private multi-agent RAG assistant optimized for AMD Radeon GPUs / ROCm.**

> 2026 AMD AI DevMaster Hackathon · Track 2: Development & Local Deployment of Private AI Agents

---

## 📦 Submission Materials

| File | Description |
|---|---|
| [`project_specification.pdf`](project_specification.pdf) | Track 2 Project Specification — scenarios, architecture, core capabilities, model & deployment plan, AMD GPU optimization |
| [`project_specification.md`](project_specification.md) | Markdown source of the specification |
| [`README.md`](README.md) | This file — overview, links, and quick start |
| [`demo_video.md`](demo_video.md) | Demo video link + shot-by-shot narration script |
| [`presentation.pptx`](presentation.pptx) | Supplementary presentation deck |
| [`src/`](src/) | Complete project source code (offline RAG agent) |

**Live source repository:** https://github.com/farlyfeifei/private-rag-agent

---

## 🧠 What It Is

Private RAG Agent answers complex questions over a **private knowledge base that never leaves your machine**. Chunking, embedding, retrieval, reasoning, and verification all run locally — no cloud API is invoked at runtime.

**Pipeline:** `decompose → parallel research → fact-check → synthesize`

1. **Decomposer** splits a complex question into independent sub-questions.
2. **Researchers** (n parallel agents) each retrieve from the knowledge base and write a sub-report.
3. **Fact-Checker** verifies every sub-report: per-sentence **groundedness** (n-gram overlap with retrieved source text) plus LLM-as-judge.
4. **Synthesizer** composes the final answer using **only verified content**.
5. A final groundedness + citation pass scores the whole answer; the UI shows a per-sentence verification panel.

**Key capabilities:**

- 🔒 Fully offline — data 100% local, works with the network disconnected
- 🔎 Hybrid retrieval — LLM query rewriting → ChromaDB vector + BM25 → Reciprocal Rank Fusion → cross-encoder rerank (`bge-reranker-v2-m3`)
- ✅ Verifiable answers — clickable citations open the original source with query terms highlighted; every sentence labeled supported / partial / unsupported
- ⚡ AMD Radeon / ROCm optimized — interchangeable backends (Ollama/ROCm, llama.cpp/HIP, vLLM/ROCm), GGUF quantization, VRAM-shared model singletons, multi-agent parallelism to saturate the GPU
- 🖥️ Professional dark UI — FastAPI + SSE streaming, live agent activity timeline, GPU monitor, source drawer

---

## 🚀 Quick Start

Requirements: AMD Radeon GPU (16GB+ VRAM recommended), ROCm 6.x (Linux) or Ollama (Windows), Python 3.10+.

```bash
git clone https://github.com/farlyfeifei/private-rag-agent
cd private-rag-agent
pip install -r requirements.txt

# Start local inference (simplest path)
ollama pull qwen3:8b     # LLM
ollama pull bge-m3       # embedding
ollama serve

# Ingest documents and launch the web UI
python main.py ingest data/docs/
python main.py ui        # → http://localhost:7860
```

Alternative backends and deployment paths (llama.cpp/HIP, Docker, Radeon Cloud) are documented in the [full README](src/README.md) and the [project specification](project_specification.pdf).

---

## 🎯 AMD / ROCm Optimization (40% of Track 2 score)

1. **Multi-backend inference** — llama.cpp (HIP, GGUF full offload), Ollama (ROCm), vLLM (ROCm, Radeon Cloud).
2. **Quantization** — GGUF Q4_K_M (~4.6 GB VRAM, fastest) default; Q8_0 (~8.2 GB) for quality.
3. **VRAM sharing** — embedding/reranker are module-level singletons; multi-agent parallelism loads one copy globally.
4. **GPU saturation** — n parallel researchers queue inference on the GPU concurrently, cutting multi-step research wall-clock time dramatically.
5. **Verified tooling** — `rocminfo`, `rocm-smi`, `ollama ps`, `python benchmarks/bench_amd.py`.

> CPU baseline ≈ 1.8 tokens/s (estimated, qwen3:8b). On RX 7900 / ROCm with Q4_K_M full offload, throughput is projected to improve 5–10×; the benchmark table will be filled with measured Radeon Cloud numbers.

---

## 📁 Track 2 Requirements Coverage

- ✅ Project Specification Document — `project_specification.pdf`
- ✅ Project Source Code + README — `src/`
- ✅ Demo Video — link in `demo_video.md`
- ✅ Supplementary Material — `presentation.pptx`
- ✅ English throughout

**PR title:** Track 2, MENG Yuxuan, Private RAG Agent
