# Bunker 🔒
**Your AI. Your Data. Your Machine.**

Bunker is a fully local AI agent running on AMD Radeon GPU via ROCm. It guarantees zero data exfiltration while delivering powerful multi-step reasoning, RAG, and tool execution capabilities right on your desktop or private server.

![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)
![ROCm 6.2](https://img.shields.io/badge/ROCm-6.2-red.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![AMD Hackathon 2026](https://img.shields.io/badge/AMD_Hackathon-2026-black)

## What is Bunker?
Bunker is a privacy-first AI agent designed for enterprise teams handling highly sensitive data (legal, medical, financial). By leveraging vLLM and ROCm on AMD Radeon GPUs, it runs entirely locally without sacrificing speed or reasoning power. It features a robust ReAct agent loop, local file/email integration, and a dedicated Privacy Dashboard to monitor data flow continuously.

## Features
- 🚀 **Hardware Accelerated**: Native AMD ROCm support with INT4/INT8 quantization for maximum throughput.
- 🔒 **Zero Exfiltration**: 100% local processing verified by the DataFlowMonitor.
- 🧠 **Multi-Step Reasoning**: ReAct agent paradigm with a built-in TaskPlanner for complex workflows.
- 📚 **Local RAG**: Seamless document ingestion and semantic search using ChromaDB.
- 🛠️ **Extensible Tools**: MCP-style tool registry with a rigid PermissionController for write operations.
- 📊 **Privacy Dashboard**: Real-time Gradio UI showcasing audit logs and local processing metrics.

## Quick Start
You can run Bunker entirely via Docker (recommended) or manually.

### Using Docker Compose
```bash
git clone https://github.com/monokpe/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
docker-compose up --build
```
Navigate to `http://localhost:7860` to access the UI.

### Manual Installation
```bash
python -m venv .venv310
source .venv310/bin/activate        # Windows: .venv310\Scripts\activate
pip install -r requirements.txt
```

### Running the App (API + Gradio UI)
```bash
# FastAPI app with the Gradio UI mounted at / — visit http://localhost:7860
uvicorn src.main:app --host 0.0.0.0 --port 7860
# or, equivalently:
python -m src.main
```

Useful endpoints once it is running:
- `GET /` — the Gradio UI (chat + privacy dashboard)
- `GET /health` — `{"status": "ok", "version": "1.0.0"}`
- `GET /api/privacy/status` — live local-vs-external data flow status

### Local Developer Smoke Backend (Ollama)
For low-resource Windows development, install Ollama and pull `qwen3:0.6b`. This is for local end-to-end smoke testing only — production and hackathon framing remains AMD Radeon/ROCm local inference.

```powershell
# 1. Start Ollama and pull the tiny local model
ollama serve
ollama pull qwen3:0.6b

# 2. Point Bunker at Ollama (pydantic-settings prefix: BUNKER_ + __ delimiter)
$env:BUNKER_INFERENCE__BACKEND="ollama"
$env:BUNKER_INFERENCE__OLLAMA_MODEL="qwen3:0.6b"
$env:BUNKER_INFERENCE__OLLAMA_BASE_URL="http://localhost:11434/v1"

# 3. Smoke: verifies the active config, Ollama health, and app imports
.venv310\Scripts\python.exe scripts\local_smoke.py

# 4. Offline deterministic BDD smoke (no model needed)
make test-bdd
```

## Detailed Setup
To take full advantage of AMD GPU acceleration, ensure ROCm 6.2 is installed.
1. Install ROCm following the [official AMD guide](https://rocm.docs.amd.com/).
2. Set environment variables:
   ```bash
   export HSA_OVERRIDE_GFX_VERSION=11.0.0
   ```
3. The application will automatically download the default quantized models on first run. To configure custom models, edit `src/config.py`.

### Validating AMD ROCm / Radeon Cloud
```bash
# Local ROCm stack: prints torch.version.hip, torch.cuda.is_available(),
# GPU name, and exits non-zero if ROCm is missing.
python scripts/validate_rocm.py

# Radeon Cloud API fallback (requires a key)
$env:BUNKER_INFERENCE__BACKEND="radeon_api"
$env:BUNKER_INFERENCE__RADEON_API_KEY="<your-key>"
python -c "from src.config import get_config; from src.inference.radeon_api import RadeonCloudAPI; api = RadeonCloudAPI(api_key=get_config().inference.radeon_api_key); print('Radeon Cloud available:', api.is_available()); print(api.generate([{'role': 'user', 'content': 'Say hello in one word.'}], max_tokens=8))"
```

## Architecture

```text
+-----------------------------------------------------------------+
|                         PRESENTATION LAYER                      |
|                  Gradio UI (Chat + Privacy Dashboard)           |
+-----------------------------------------------------------------+
|                           AGENT LAYER                           |
|       ReActAgent | TaskPlanner | PermissionController           |
+-----------------------------------------------------------------+
|                          SERVICES LAYER                         |
|   Memory (SQLite)  |  RAG (ChromaDB)   |  Tools (File, Email)   |
+-----------------------------------------------------------------+
|                        INFERENCE LAYER                          |
|         vLLM (ROCm)  |  Local Fallback |  Radeon Cloud API      |
+-----------------------------------------------------------------+
|                         HARDWARE LAYER                          |
|                     AMD Radeon GPU (MI300X/RX7900)              |
+-----------------------------------------------------------------+
```

## Performance Benchmarks
*Tested on AMD Radeon RX 7900 XTX (24GB), ROCm 6.2*

| Precision | TTFT (ms) | Throughput (tok/s) | VRAM (GB) |
| :--- | :--- | :--- | :--- |
| INT8 (GPTQ) | 125 | 35 | 18 |
| INT4 (GPTQ) | 85 | 65 | 11 |

## Five Capabilities
1. **RAG**: Automatically index and retrieve contextual data from your local documents.
2. **Tool Invocation**: Agent can read/write files, draft emails, and check your calendar.
3. **Multi-Step Planning**: Complex requests are broken down into logical steps.
4. **Multi-Turn Memory**: Infinite context memory backed by SQLite and token-aware trimming.
5. **Permission Control**: Strict human-in-the-loop gating for irreversible actions.

## Privacy Architecture
Bunker is designed for absolute privacy. The `AuditLogger` records all operations to a local file. The `DataFlowMonitor` continuously verifies that 100% of data traffic remains on `localhost`. Any attempt by the agent to write files or send emails is intercepted by the `PermissionController`, requiring explicit user consent via the UI. Furthermore, all persistent RAG indices and SQLite databases are encrypted at rest using AES-256 via the `DataEncryptor`.

## Testing
The suite is layered; run it with `make` targets or pytest directly. Live-model
tests (integration, live perf probes) skip automatically when no server is on
`:8000`; perf VRAM and security "Deny" checks use deterministic mocks
everywhere so the whole suite is green on any machine.

```bash
make test-unit       # offline gate: 117 tests (+ 1 env-dependent skip)
make test-integration
make test-eval       # skips until artifacts/bunker_rag_mipro.json is compiled
make test-perf
make test-security
make test-negative
make test-compile
make test-bdd        # behave/Gherkin acceptance suite (4 scenarios, 23 steps)
make test-all        # every layer, end to end
```

Or run the offline-only gate directly:

```bash
pytest tests -m "not integration and not eval" -q
```

> **Generated artifacts:** `artifacts/` is gitignored and not committed.
> `make test-eval` skips (never fails) until you generate
> `artifacts/bunker_rag_mipro.json` with `python scripts/compile_bunker.py`
> against a live local model.

## Contributing
We welcome contributions! Please read `CONTRIBUTING.md` for guidelines on pull requests, coding standards, and adding new MCP tools.

## License
This project is licensed under the MIT License - see the LICENSE file for details.
