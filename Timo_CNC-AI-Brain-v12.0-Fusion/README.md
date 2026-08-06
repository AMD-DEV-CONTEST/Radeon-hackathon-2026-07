# CNC-AI-Brain v12.0 Fusion

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-12.0--Fusion-orange.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey.svg)

> AI-powered CNC machining brain with TOT (Tree-of-Thought) multi-pipeline competition, real-time 3D preview, instant quoting, and CAD file parsing.

CNC-AI-Brain v12.0 Fusion is an intelligent CNC machining quotation and process planning system. It fuses multiple AI pipelines (LLM / regex / knowledge base) into a Tree-of-Thought (TOT) competition framework, automatically selecting the best result for each task. The system supports real-time 3D preview of STEP/STL files, instant quoting across 24 materials and 14 surface treatments, DFM (Design for Manufacturing) conflict detection, and parsing of PDF / DWG / DXF / XLSX / ZIP engineering documents.

---

## Table of Contents

- [Core Features](#core-features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

---

## Core Features

| Feature | Description |
|---------|-------------|
| **TOT 3-Pipeline Competition** | LLM, regex, and knowledge-base pipelines run in parallel; the best result is selected via a scoring jury |
| **STEP / STL Generation** | Native STEP generation via OpenCascade (OCP) and CadQuery; STL mesh export via trimesh |
| **Instant Quoting** | 24 materials × 14 surface treatments, with precision / 5-axis / wire-EDM surcharges |
| **Multi-Format Parsing** | PDF (pdfplumber), DWG/DXF (ezdxf), XLSX BOM (openpyxl), ZIP bundle extraction |
| **VLM Image Understanding** | PaddleOCR + MiMO VLM for image-based requirement extraction |
| **3D Preview** | Three.js in-browser preview of uploaded STEP/STL files |
| **DFM Conflict Detection** | Hard rules for material × surface-treatment compatibility (e.g. 304 stainless + anodizing is rejected) |
| **Model Auto-Discovery** | 12 cloud APIs auto-discovered via environment variables; Ollama local models auto-detected |
| **Graceful Fallback** | Cloud failure automatically falls back to local models with zero downtime |
| **One-Click Pipeline** | Generate → Detect → Quote → Export in a single request |

---

## Tech Stack

**Backend**
- Python 3.11
- FastAPI + uvicorn
- pydantic v2

**CAD / 3D**
- OpenCascade (OCP) — STEP geometry kernel
- CadQuery — parametric CAD
- trimesh — mesh / STL
- numpy-stl

**Document Parsing**
- pdfplumber — PDF
- ezdxf — DWG / DXF
- openpyxl — XLSX BOM
- PIL — image

**AI / VLM**
- OpenAI-compatible cloud APIs (DeepSeek, OpenAI, Anthropic, Qwen, Moonshot, Groq, xAI, OpenRouter, SiliconFlow, ...)
- Ollama (local)
- PaddleOCR + MiMO VLM (image understanding)

**Frontend (3D Preview)**
- Three.js

**Storage**
- SQLite (audit + orders + RAG)

**Logging**
- loguru

---

## Quick Start

### Prerequisites

- Python 3.11.x (tested on 3.11.10)
- Windows / Linux / macOS
- (Optional) [Ollama](https://ollama.com) for local model inference

### Installation

```bash
# 1. Clone the repository
git clone <repo-url> cnc-ai-brain
cd cnc-ai-brain

# 2. Create virtual environment
python -m venv .venv

# 3. Activate
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

### Run

```bash
# Start the server (port 7862)
python run_server.py

# Or via uvicorn directly
python -m uvicorn app.main:app --host 0.0.0.0 --port 7862
```

Open the browser: **http://127.0.0.1:7862**

### Windows One-Click

```cmd
install_windows.bat
一键启动.bat
```

### Linux One-Click

```bash
chmod +x install_linux.sh
./install_linux.sh
```

---

## Configuration

### Model Selection — `config/models.json`

Edit `config/models.json` to manually select cloud or local models:

```json
{
  "default": "deepseek-chat",
  "fallback": ["qwen2.5:1.5b", "ollama-default"],
  "models": {
    "deepseek-chat": { "provider": "deepseek", "model": "deepseek-chat" }
  }
}
```

### Environment Variables (Auto-Discovery)

The system auto-discovers cloud APIs from these environment variables:

| Variable | Provider |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `SILICONFLOW_API_KEY` | SiliconFlow |
| `QWEN_API_KEY` | Alibaba Qwen |
| `XAI_API_KEY` | xAI Grok |
| `OPENROUTER_API_KEY` | OpenRouter |
| `GROQ_API_KEY` | Groq |
| `MOONSHOT_API_KEY` | Moonshot Kimi |

### TOT / VLM Toggles

| Variable | Default | Description |
|----------|---------|-------------|
| `TOT_ENABLED` | `1` | Enable Tree-of-Thought pipeline competition |
| `VLM_API_URL` | — | VLM service endpoint for image understanding |
| `VLM_API_KEY` | — | VLM service API key |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama local server |

### Local Model (Ollama)

```bash
# Install Ollama: https://ollama.com
ollama pull qwen2.5:1.5b
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | AI dialogue (TOT multi-pipeline) |
| `/api/upload` | POST | Upload CAD / PDF / DWG / DXF / XLSX / ZIP |
| `/api/upload-step` | POST | Upload STEP file and generate 3D preview |
| `/api/quote` | POST | Instant quoting |
| `/api/models` | GET | List available models |
| `/api/models/switch` | POST | Switch model at runtime |
| `/api/models/fallback` | GET | Show fallback chain |
| `/api/dashboard` | GET | Dashboard statistics |
| `/api/one-click` | POST | Full pipeline: generate → detect → quote → export |
| `/api/health` | GET | Health check |
| `/api/audit` | GET | Audit log |

Interactive docs: **http://127.0.0.1:7862/docs** (Swagger UI)

---

## Project Structure

```
cnc-ai-brain/
├── app/                          # FastAPI application
│   ├── main.py                   # Main app entry (routes, TOT pipeline)
│   ├── main_lite.py              # Lite mode entry
│   ├── cnc_quick.py              # Quick quoting service
│   └── static/                   # Frontend assets (Three.js preview)
├── src/                          # Core source
│   ├── ai_engine/                # AI engines (engine, ollama, openai)
│   ├── core/                     # Core (env detector, model auto-loader, registry)
│   ├── data/                     # RAG engine
│   ├── neuro_core/               # Conflict check, reasoning chain, schema validator
│   ├── runtime/                  # CAD pipeline TOT, STEP generator, quote adapter
│   └── safety/                   # Audit logger
├── config/                       # Configuration
│   ├── models.json               # Model selection
│   ├── tolerance.yaml            # Tolerance rules
│   ├── experts/                  # Expert prompts
│   └── skills/                   # Skill definitions
├── data/                         # Runtime data (gitignored)
│   ├── documents/
│   ├── exports/
│   ├── step/
│   └── uploads/
├── docs/                         # Documentation
│   ├── ARCHITECTURE.md           # Architecture overview
│   └── product_brochure.md
├── tests/                        # Test suite
│   ├── test_cad_tot.py
│   └── e2e_api_test_task7.py
├── scripts/                      # Utility scripts
├── deploy/                       # Deployment configs
├── templates/                    # Templates
├── run_server.py                 # Server launcher
├── requirements.txt              # Dependencies
├── pyproject.toml                # Project metadata
├── Dockerfile                    # Container image
├── docker-compose.yml            # Container orchestration
├── .gitignore
├── LICENSE
├── CONTRIBUTING.md
└── README.md
```

---

## Testing

```bash
# Activate virtual environment first
.venv\Scripts\activate

# Run the CAD TOT test suite
pytest tests/test_cad_tot.py -v

# Run end-to-end API tests
pytest tests/e2e_api_test_task7.py -v

# Run all tests
pytest tests/ -v
```

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system architecture, including:

- TOT pipeline competition mechanism
- Model auto-discovery
- File parsing pipeline
- Quoting engine
- 3D preview pipeline

---

## Demo Video

- Bilibili: https://www.bilibili.com/video/BV1yGuE6JEf5/?vd_source=8eb1add0760aa9059b9428c508bc1393
- Repository: `Timo_CNC-AI-Brain-v12.0-Fusion/demo_Video/demo_video_20260806.mp4`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Reporting bugs
- Submitting pull requests
- Coding standards (snake_case, no hardcoding, DRY)
- Testing requirements

---

## License

MIT License — see [LICENSE](LICENSE).
