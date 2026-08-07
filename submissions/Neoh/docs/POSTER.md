# Radeon-Assistant — Single-Page Poster

> English single-page poster for AMD Radeon Hackathon 2026-07, Track 2.  
> Rendered asset: [`poster.png`](poster.png)  
> Generator: [`generate_poster.py`](../scripts/generate_poster.py)

---

## Header

**Radeon-Assistant**

A Privacy-First Local AI Agent on AMD Radeon GPU

AMD Radeon Hackathon 2026-07 · Track 2 — Private AI Agent Development & Local Deployment · Team: Neoh

---

## Application Scenario

All LLM inference, embedding, and vector search run locally on an AMD Radeon GPU via vLLM + ROCm. No external API is called during inference, making the system ideal for data-privacy, offline, and on-premise AI-assistant use cases.

Scenarios:
- Local RAG Q&A
- Office Automation
- Multi-Step Planning
- Hardware R&D
- Privacy-First

---

## Core Capabilities

1. **Local RAG Knowledge Base**  
   FAISS + all-MiniLM-L6-v2; PDF / DOCX / MD / TXT with table extraction.

2. **Tool Calling**  
   14 built-in tools across file / shell / code / system / hardware categories.

3. **Multi-Step Planning**  
   Planner → Executor → Reflector loop with self-reflection and retry.

4. **Local Multi-Turn Memory**  
   Short-term buffer (20 msgs) + long-term FAISS vector retrieval.

5. **Permission & Privacy**  
   Human-in-the-loop approval gate + JSON-Lines audit logging.

---

## System Architecture

Embedded diagram: [`architecture.png`](architecture.png)

Layered design: UI → Agent → Safety → Tools → Memory → Inference → AMD Radeon GPU.

Architecture generator: [`generate_architecture.py`](../scripts/generate_architecture.py)

---

## AMD ROCm Inference Optimization

Optimized for AMD Radeon (ROCm 7.14, gfx1100). vLLM PagedAttention + continuous batching, ROCm graph capture, and configurable single-GPU tensor parallelism.

| GPU | Model | Speed | VRAM |
|---|---|---|---|
| Radeon Pro W7900 | Qwen2.5-14B FP16 | 27.5 tok/s | ~30 GB |
| Radeon Pro W7900 | Qwen2.5-7B FP16 | 46 tok/s | ~15 GB |

Measured on AMD Radeon Cloud (Radeon Pro W7900D, 48 GB VRAM, single GPU, ROCm 7.14, vLLM 0.23.1, Python 3.14).

---

## Footer

- **Repository:** github.com/RainmeoX/Radeon-hackathon-2026-07 (submissions/Neoh)
- **Demo:** local Web UI + CLI (no cloud dependency) — demo video included in repository
- **Privacy note:** All inference runs locally on AMD Radeon — no external API is called.
