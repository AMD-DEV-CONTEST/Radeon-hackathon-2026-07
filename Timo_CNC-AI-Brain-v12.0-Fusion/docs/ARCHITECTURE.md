# Architecture — CNC-AI-Brain v12.0 Fusion

This document describes the system architecture of CNC-AI-Brain v12.0 Fusion, including the TOT pipeline competition mechanism, model auto-discovery, file parsing pipeline, quoting engine, and 3D preview pipeline.

---

## Table of Contents

- [System Overview](#system-overview)
- [Module Map](#module-map)
- [TOT Pipeline Competition](#tot-pipeline-competition)
- [Model Auto-Discovery](#model-auto-discovery)
- [File Parsing Pipeline](#file-parsing-pipeline)
- [Quoting Engine](#quoting-engine)
- [3D Preview Pipeline](#3d-preview-pipeline)
- [Data Flow](#data-flow)

---

## System Overview

CNC-AI-Brain v12.0 Fusion is a FastAPI-based service that fuses multiple AI pipelines into a Tree-of-Thought (TOT) competition framework. The system accepts user requests (chat, upload, quote) and routes them through parallel pipelines. A scoring jury selects the best result, which is then returned to the user. The system supports cloud LLMs, local Ollama models, regex-based extractors, and a knowledge base, with automatic fallback when a provider fails.

```
┌─────────────────────────────────────────────────────────────┐
│                        Client (Browser)                      │
│                  Three.js 3D Preview + Chat UI               │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP / WebSocket
┌────────────────────────────▼────────────────────────────────┐
│                     FastAPI (app/main.py)                    │
│  /api/chat  /api/upload  /api/quote  /api/models  /api/...   │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                  TOT Pipeline Orchestrator                   │
│   (src/runtime/cad_pipeline_tot.py, src/neuro_core/)         │
└──┬──────────────────┬──────────────────┬───────────────────┘
   │ Pipeline A       │ Pipeline B       │ Pipeline C
┌──▼──────┐      ┌────▼─────┐      ┌────▼──────────┐
│  LLM    │      │  Regex   │      │ Knowledge Base│
│ (cloud/ │      │ Extractor│      │  + RAG Engine │
│  local) │      │          │      │                │
└──┬──────┘      └────┬─────┘      └────┬──────────┘
   │                  │                  │
   └──────────┬───────┴──────────────────┘
              │
   ┌──────────▼──────────┐
   │   Scoring Jury       │
   │  (best result wins)  │
   └──────────┬──────────┘
              │
┌─────────────▼───────────────────────────────────────────────┐
│              Output: Quote / STEP / STL / Report             │
└──────────────────────────────────────────────────────────────┘
```

---

## Module Map

| Module | Path | Responsibility |
|--------|------|----------------|
| **API Layer** | `app/main.py` | FastAPI routes, request dispatch, TOT orchestration |
| **Lite Mode** | `app/main_lite.py` | Reduced-feature entry for low-resource environments |
| **Quick Quote** | `app/cnc_quick.py` | Lightweight quoting service |
| **AI Engines** | `src/ai_engine/` | LLM engine abstraction (Ollama, OpenAI-compatible) |
| **Core** | `src/core/` | Environment detector, model auto-loader, model registry, skill auto-loader |
| **RAG** | `src/data/rag_engine.py` | Retrieval-augmented generation over knowledge base |
| **Neuro Core** | `src/neuro_core/` | Conflict check, reasoning chain, schema validator, serial expert |
| **Runtime** | `src/runtime/` | CAD pipeline TOT, STEP generator (OCP / CadQuery / dual), STEP parser, quote adapter, XLSX generator, export bundler, event bus, progress reporter, history lookup, skill caller |
| **Safety** | `src/safety/audit_logger.py` | Audit logging to SQLite |
| **Config** | `config/` | `models.json`, `tolerance.yaml`, expert prompts, skill definitions |
| **Tests** | `tests/` | `test_cad_tot.py`, `e2e_api_test_task7.py` |

---

## TOT Pipeline Competition

The Tree-of-Thought (TOT) competition is the core innovation of v12.0 Fusion. For each user request, multiple pipelines run in parallel and a scoring jury selects the best result.

### Pipelines

| Pipeline | Source | Strength |
|----------|--------|----------|
| **LLM** | `src/ai_engine/` (cloud or Ollama) | Natural-language reasoning, flexible extraction |
| **Regex** | `src/runtime/` extractors | Deterministic, fast, zero-cost |
| **Knowledge Base** | `src/data/rag_engine.py` + `config/experts/` | Domain rules, historical cases, DFM constraints |

### Competition Flow

1. **Fan-out**: The orchestrator (`cad_pipeline_tot.py`) dispatches the same input to all enabled pipelines.
2. **Parallel execution**: Each pipeline produces a candidate result.
3. **Scoring jury**: Each candidate is scored on:
   - Schema validity (`schema_validator.py`)
   - Field completeness
   - DFM conflict freedom (`conflict_check.py`)
   - Domain plausibility (reasoning chain score)
4. **Selection**: The highest-scoring candidate wins. Ties are broken by pipeline priority (LLM > KB > Regex).
5. **Fallback**: If the winning pipeline is a cloud LLM and the response is invalid, the system falls back to the next-best candidate without downtime.

### Toggle

Set `TOT_ENABLED=0` to disable competition and use a single pipeline (default: LLM with fallback).

---

## Model Auto-Discovery

The system auto-discovers available AI models at startup via `src/core/environment_detector.py` and `src/core/model_auto_loader.py`.

### Discovery Sources

1. **Environment variables** — 12 cloud providers are auto-detected:
   - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `SILICONFLOW_API_KEY`, `QWEN_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `MOONSHOT_API_KEY`, ...
2. **Ollama local** — `http://127.0.0.1:11434/api/tags` is polled for installed local models.
3. **`config/models.json`** — manual override of the default / fallback chain.

### Registry

`src/core/model_registry.py` maintains the live registry of available models. At runtime, models can be switched via `POST /api/models/switch` and the fallback chain inspected via `GET /api/models/fallback`.

### Fallback Chain

```
cloud-primary → cloud-secondary → ollama-local → regex (offline guarantee)
```

If a cloud provider fails (network, rate limit, invalid response), the system automatically falls back to the next provider in the chain. The regex pipeline always remains as the final offline guarantee.

---

## File Parsing Pipeline

The system parses multiple engineering document formats and extracts structured part specifications.

```
Upload → MIME detect → Format-specific parser → PartSpec → TOT pipeline
```

| Format | Parser | Output |
|--------|--------|--------|
| **STEP / STP** | `src/runtime/step_parser.py` (OpenCascade) | Geometry, bounding box, volume, faces |
| **STL** | trimesh | Mesh, volume, surface area |
| **PDF** | pdfplumber | Text → LLM extraction → PartSpec |
| **DWG / DXF** | ezdxf | Geometry, dimensions → PartSpec |
| **XLSX** | openpyxl | BOM table → PartSpec list |
| **ZIP** | stdlib `zipfile` | Bundle extraction → recursive parse |
| **Image** | PaddleOCR + MiMO VLM | OCR text + VLM understanding → PartSpec |

All parsers produce a unified `PartSpec` schema validated by `src/neuro_core/schema_validator.py`.

---

## Quoting Engine

The quoting engine computes instant quotes from a validated `PartSpec`.

### Inputs

- Material (24 supported: aluminum 6061/7075, steel 1018/1045/A36, stainless 304/316, titanium, brass, copper, ...)
- Surface treatment (14 supported: anodizing, powder coating, electroplating, sandblasting, polishing, ...)
- Geometry: bounding box, volume, complexity
- Tolerance / precision class
- Process: 3-axis milling, 5-axis milling, wire EDM, turning

### Cost Components

| Component | Source |
|------------|--------|
| Material cost | volume × density × material price |
| Machining cost | estimated machining time × hourly rate |
| Surface treatment cost | treatment-specific rate × area |
| Precision surcharge | tolerance class multiplier |
| 5-axis surcharge | applied when 5-axis required |
| Wire-EDM surcharge | applied when wire-EDM selected |

### DFM Conflict Detection

Before quoting, `src/neuro_core/conflict_check.py` validates material × surface-treatment compatibility against hard rules. Example: 304 stainless steel + anodizing is rejected (stainless steel cannot be anodized). Conflicts are returned as errors and never produce a quote.

### Output

Quotes are returned as JSON via `POST /api/quote` and can be exported as XLSX via `src/runtime/quote_xlsx_generator.py` or bundled into a ZIP via `src/runtime/export_bundler.py`.

---

## 3D Preview Pipeline

The 3D preview pipeline converts uploaded CAD files into browser-renderable meshes.

```
STEP upload → OpenCascade (OCP) load → tessellate → STL mesh
   → Three.js (frontend) → interactive preview
```

1. **Server side** (`/api/upload-step`): The STEP file is loaded via OpenCascade, tessellated into a triangle mesh, and converted to STL format.
2. **Client side** (`app/static/`): Three.js loads the STL mesh and renders an interactive preview with orbit controls, wireframe toggle, and measurement tools.

For STL uploads, the file is passed directly to Three.js after a trimesh validation step.

---

## Data Flow

```
User Request
    │
    ├─ /api/chat ───────────→ TOT pipeline ──→ AI response
    │
    ├─ /api/upload ─────────→ File parser ──→ PartSpec ──→ TOT pipeline
    │
    ├─ /api/upload-step ────→ STEP parser ──→ STL mesh ──→ 3D preview
    │
    ├─ /api/quote ──────────→ PartSpec ──→ DFM check ──→ Quote engine ──→ Quote JSON
    │
    └─ /api/one-click ──────→ Upload → Parse → Generate STEP → DFM check → Quote → Export ZIP
```

All actions are logged via `src/safety/audit_logger.py` to the SQLite audit database (`data/audit.db`).

---

## References

- [README.md](../README.md)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [LICENSE](../LICENSE)