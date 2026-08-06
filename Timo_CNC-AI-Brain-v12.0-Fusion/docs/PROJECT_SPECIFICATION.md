# Project Specification Document — UnionSkill CNC-AI-Brain v12.0 Fusion

**Track:** 2 — Development & Local Deployment of Private AI Agents  
**Team:** timo曹冬冬  
**Application:** UnionSkill CNC-AI-Brain  
**Repository:** https://github.com/Timo2026/Radeon-hackathon-2026-07  
**Contact:** 849355070@qq.com

---

## 1. Application Scenarios

CNC-AI-Brain is a private AI agent for non-standard CNC machining quotation and manufacturing intelligence. It targets workshops and factories that need instant, offline-capable quoting from engineering files.

- **Instant quoting:** Upload STEP/STL/PDF/DWG/DXF/XLSX/ZIP → the agent parses geometry and material requirements, runs a Tree-of-Thought (TOT) competition across LLM / regex / knowledge-base pipelines, and returns a quotation in seconds.
- **DFM conflict detection:** Hard rules reject incompatible material × surface-treatment combinations before quoting (e.g., 304 stainless + anodizing), preventing non-manufacturable orders.
- **Offline / edge deployment:** Cloud-first with automatic fallback to local Ollama models; zero external dependency guarantees when cloud APIs fail.
- **3D preview & audit:** Browser-based Three.js preview of CAD files; every quote and decision is logged to SQLite for traceability.

---

## 2. Agent Architecture

```
Client (Browser / API)
        │
        ▼
FastAPI Gateway (app/main.py)
        │
        ▼
TOT Orchestrator (src/runtime/cad_pipeline_tot.py)
   ┌──────────┬──────────┬──────────┐
   │ Pipeline │ Pipeline │ Pipeline │
   │   A      │   B      │   C      │
   │  LLM     │  Regex   │   KB     │
   └────┬─────┴────┬─────┴────┬────┘
        │          │          │
        ▼          ▼          ▼
   Scoring Jury (schema + completeness + DFM + plausibility)
        │
        ▼
   Best Result → Quote JSON / STEP / STL / Report
```

- **Orchestrator:** dispatches the same input to all enabled pipelines in parallel; selects the winner via a scoring jury.
- **Pipeline A — LLM:** cloud OpenAI-compatible APIs or local Ollama; handles flexible extraction and reasoning.
- **Pipeline B — Regex:** deterministic extractors for dimensions, tolerances, quantities; zero token cost.
- **Pipeline C — Knowledge Base:** RAG engine over 14,000+ industrial knowledge entries and DFM rules.
- **Safety / Audit:** `src/safety/audit_logger.py` records every decision to SQLite.

---

## 3. Core Capabilities

| Capability | Implementation |
|------------|----------------|
| Multi-format engineering document parsing | pdfplumber / ezdxf / openpyxl / OpenCascade / trimesh |
| Instant CNC quotation | 24 materials × 14 surface treatments; precision / 5-axis / wire-EDM surcharges |
| DFM conflict detection | Hard rule engine in `src/neuro_core/conflict_check.py` |
| Tree-of-Thought pipeline competition | LLM + regex + KB race; scoring jury selects the best |
 3D preview | Three.js in-browser STEP/STL viewer |
| Model auto-discovery | 12 cloud providers via environment variables; Ollama local auto-detection |
| Graceful fallback | Cloud → local → regex; zero downtime |
| One-click pipeline | Generate → Detect → Quote → Export ZIP in one request |
| Local deployment | Docker image + Linux/Windows one-click installers |

---

## 4. Model Introduction & Local Deployment Plan

### Models

- **Cloud LLMs:** OpenAI-compatible APIs (DeepSeek, OpenAI, Anthropic, Qwen, Moonshot, Groq, xAI, OpenRouter, SiliconFlow, etc.). Auto-discovered via environment variables.
- **Local LLM:** Ollama with `qwen2.5:1.5b` as the default offline brain (1.5B, CPU-friendly, zero cost).
- **VLM / OCR:** PaddleOCR + MiMO VLM for image-based requirement extraction.

### Local Deployment Plan

1. **Docker (recommended):**
   ```bash
   docker compose up --build
   ```
   Image includes Python 3.11, FastAPI, OpenCascade, CadQuery, trimesh, pdfplumber, ezdxf, PaddleOCR.

2. **Linux bare metal:**
   ```bash
   chmod +x install_linux.sh
   ./install_linux.sh
   python run_server.py
   ```

3. **Windows bare metal:**
   ```cmd
   install_windows.bat
   一键启动.bat
   ```

4. **Configuration:** `config/models.json` defines the default and fallback chain; environment variables override cloud providers at runtime.

---

## 5. Optimization Description for AMD Radeon GPU / ROCm

CNC-AI-Brain is built on an abstraction layer that separates AI inference from hardware backends. While current production runs on x86 CPU / NVIDIA / cloud APIs, the architecture is designed for AMD ROCm portability.

### Current baseline

- **Inference:** OpenAI-compatible client layer (`src/ai_engine/`) talks to cloud APIs or local Ollama.
- **Local model:** `qwen2.5:1.5b` via Ollama (CPU/GPU agnostic).
- **CAD / mesh:** OpenCascade, CadQuery, trimesh — all pure Python/C++ with no CUDA-specific kernels.

### ROCm migration path (inference)

1. Replace Ollama with a ROCm-enabled runtime (e.g., PyTorch ROCm wheels + llama.cpp ROCm build) for the 1.5B local model. Because the system uses the standard OpenAI-compatible API surface, the backend swap requires only base-image and startup-script changes.
2. Cloud-LLM paths remain unchanged; ROCm benefits the offline / local pipeline most.

### ROCm migration path (CAD / mesh)

- OpenCascade, CadQuery, and trimesh do not depend on CUDA. On AMD Radeon GPUs they run on CPU or via ROCm-accelerated PyTorch if mesh operations are routed through tensor backends. No code changes are required for CPU-only execution.

### Reproducibility

A `Dockerfile` and `docker-compose.yml` are included. For AMD ROCm reproduction, replace the base image with an AMD ROCm PyTorch image and rebuild; the Python dependency graph is fully captured in `requirements.txt` and `requirements-locked.txt`.

---

## 6. Team Members

- **timo (曹冬冬)** — system architecture, agent orchestration, quoting engine, DFM rules, hackathon integration.

---

## References

- Source code: `Timo_CNC-AI-Brain-v12.0-Fusion/` in this repository
- Architecture: `docs/ARCHITECTURE.md`
- Product overview: `docs/product_brochure.md`
- Demo video: `demo_Video/8月6日.mov`
- Poster: `demo_PPT/Unionskill_Timo.pdf`
