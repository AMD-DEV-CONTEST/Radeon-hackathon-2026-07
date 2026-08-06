# BuildGuard-Radeon

BuildGuard-Radeon is a local AI agent for construction inspection and risk decision-making on AMD Radeon/ROCm. It integrates a local LLM, a LangGraph agent, hybrid RAG, image inspection, real-time video events, risk scoring, SQLite task memory, a FastAPI API, a Streamlit workbench, and evaluation tools.

## Environment Requirements

### AMD GPU Server (production)

| Requirement | Validated version |
|-------------|------------------|
| OS | Linux (Ubuntu 22.04 recommended) |
| GPU | AMD Radeon RX 7900 XTX (gfx1100) or compatible RDNA3/RDNA2 |
| ROCm | 7.2.1 — must be installed at OS level before running bootstrap |
| Python | 3.12 |
| PyTorch | 2.9.1+rocm7.2.1 |
| torchvision | 0.24.1 (CPU NMS — ROCm NMS kernel not yet available) |
| uv | latest — bootstrap installs it automatically |

**First-time setup on a blank server:**

```bash
git clone <repository-url> /persistent/BuildGuard-Radeon-backup
cd /persistent/BuildGuard-Radeon-backup
bash scripts/bootstrap.sh
```

`bootstrap.sh` handles everything after ROCm: installs `uv`, creates the Python 3.12 venv at `envs/app-py312-rocm721`, installs PyTorch with ROCm support, downloads the `llama-server` binary, and downloads all model weights (LLM, embedding, reranker, vision). Re-running it is safe — already-downloaded files are skipped.

Override the mirror if needed (default is `hf-mirror.com` for China):

```bash
HF_MIRROR=https://huggingface.co bash scripts/bootstrap.sh
```

The production venv lives at `envs/app-py312-rocm721`. **Do not use `.venv/`** — it contains a CUDA PyTorch build and is incompatible with ROCm.

The validated pip constraints are in `constraints/rocm-7.2.1-py312.txt`. See [ROCm Setup](docs/ROCM_SETUP.md) and the [AMD Server Runbook](docs/AMD_SERVER_RUNBOOK_CN.md) for details.

### Development / mock (Windows, Linux, macOS)

- Python `>=3.11,<3.13`
- uv (`pip install uv`) or plain pip + venv
- Git
- Optional: Docker and Docker Compose v2

Windows supports development, testing, and mock demonstrations (no GPU required).

**Linux/macOS:**

```bash
git clone <repository-url>
cd BuildGuard-Radeon
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

**Windows PowerShell:**

```powershell
git clone <repository-url>
cd BuildGuard-Radeon
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If PowerShell blocks the activation script: `Set-ExecutionPolicy -Scope Process Bypass`

### Optional feature sets

```bash
pip install -e '.[pdf]'          # PDF report export (requires weasyprint system deps)
pip install -e '.[vision-onnx]'  # ONNX runtime for vision models
pip install -e '.[amd]'          # AMD evaluation utilities (scipy, pycocotools)
pip install -e '.[mobileclip]'   # MobileCLIP2 semantic router
pip install -e '.[dev,amd,pdf,mobileclip]'  # everything at once
```

## Startup Guide

### AMD GPU Server

All services are managed by scripts that read layout from `scripts/server_env.sh` (override any variable with an env var).

**Default paths (persistent volume layout):**

| Variable | Default |
|----------|---------|
| `BG_PVC` | `/persistent/BuildGuard-Radeon-backup` |
| `BG_REPO` | `$BG_PVC` |
| `BG_VENV` | `$BG_PVC/envs/app-py312-rocm721` |
| `BG_MODELS` | `$BG_PVC/models` |
| `BG_CONFIG` | `$BG_REPO/configs/competition/app.yaml` |

**Start everything (llama-server → API → UI):**

```bash
cd /persistent/BuildGuard-Radeon-backup
scripts/start_all.sh
```

The script waits for each service in sequence, showing `launching... (Xs elapsed)` while polling. Typical startup: LLM ~90 s, API ~60 s, UI ~30 s.

**Stop everything:**

```bash
scripts/stop_all.sh
```

**SSH tunnel (run on local machine):**

```bash
ssh -L 18000:127.0.0.1:8000 -L 18501:127.0.0.1:8501 amd -N
```

After the tunnel is up:

- Streamlit UI: <http://localhost:18501>
- API: <http://localhost:18000>
- Swagger docs: <http://localhost:18000/docs>
- Health check: <http://localhost:18000/health>

**Run individual services:**

```bash
scripts/start_local_llm.sh    # llama-server on :8080
scripts/start_api.sh          # FastAPI on :8000
scripts/start_ui.sh           # Streamlit on :8501
scripts/stop_api.sh
scripts/health_check.sh
```

### Development / Mock (no GPU)

```bash
buildguard validate-config --config configs/app.yaml
buildguard init-workspace --config configs/app.yaml
buildguard db-init --config configs/app.yaml
buildguard smoke-test --config configs/app.yaml
pytest -q
buildguard run-demo --config configs/app.yaml
```

Or run API and UI in separate terminals:

```bash
buildguard serve-api --config configs/app.yaml
buildguard serve-ui --config configs/app.yaml
```

### Docker Mock Demo

```bash
# API only (no GPU)
docker compose --profile mock up --build

# API + UI
docker compose --profile full-demo up --build

# Stop
docker compose --profile full-demo down
```

### Docker ROCm

Copy the example env file and configure image paths and devices, then:

```bash
cp competition.env.example .env
docker compose --profile rocm-app up --build
```

ROCm containers require `/dev/kfd`, `/dev/dri`, and the correct render/video group permissions.

## Configuration

- `configs/app.yaml`: the Windows/general development entry point; combines the LLM, permissions, RAG, vision, real-time video, service, and other configurations from the same directory.
- `configs/competition/app.yaml`: the AMD competition environment entry point; all persistent paths should reside under `/workspace/persistent/buildguard`.
- `configs/llm.yaml`: LLM mode, endpoint, model, and generation parameters.
- `configs/services.yaml`: API/UI addresses and ports.
- `configs/permissions.yaml`: file roots, network ranges, confirmation rules, and audit policies.
- `configs/rag.yaml`, `vision.yaml`, and `realtime.yaml`: retrieval, vision, and video pipelines.

See the [Configuration Reference](docs/CONFIGURATION_REFERENCE.md) for the complete field descriptions.

## Dependencies

`pyproject.toml` is the authoritative dependency declaration.

| Category | Dependencies |
| --- | --- |
| Configuration and CLI | `pydantic`, `pydantic-settings`, `typer`, `rich`, `pyyaml` |
| API and networking | `fastapi`, `uvicorn`, `httpx`, `tenacity` |
| Agent and structured output | `langgraph`, `langchain-core`, `json-repair`, `orjson` |
| Database and system | `sqlalchemy`, `alembic`, `psutil` |
| RAG and documents | `rank-bm25`, `faiss-cpu`, `transformers`, `sentencepiece`, `pypdf`, `python-docx` |
| Vision and computation | `torch`, `ultralytics`, `numpy`, `opencv-python-headless`, `pillow` |
| UI and reports | `streamlit`, `jinja2`, `markdown`, `pandas`, `matplotlib` |
| Development (`dev`) | `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `types-PyYAML`, `types-psutil` |
| Optional `vision-onnx` | `onnxruntime` |
| Optional `pdf` | `weasyprint` (may require system-level fonts and rendering libraries) |
| Optional `amd` | `scipy>=1.10`, `pycocotools>=2.0.7` |
| Optional `mobileclip` | `open-clip-torch>=3.2,<4` |

`deployment/requirements-server.txt` is a frozen snapshot of a specific server environment for auditing and reproduction. It is not intended as the general installation entry point for every platform.

## Common Commands

```bash
# Show all commands
buildguard --help

# Database and runtime environment
buildguard db-check --config configs/app.yaml
buildguard probe-environment --config configs/app.yaml

# Local RAG
buildguard rag-ingest <document-or-directory-under-an-allowed-root> --config configs/app.yaml
buildguard rag-search "hard-hat requirements" --config configs/app.yaml
buildguard rag-status --config configs/app.yaml

# Full evaluation (mock results are not competition results)
buildguard benchmark-suite --config configs/app.yaml
```

## Further Documentation

- [Project Overview](docs/PROJECT_OVERVIEW_CN.md)
- [System Architecture](docs/ARCHITECTURE.md)
- [Vision Setup](docs/VISION_SETUP.md)
- [RAG Setup](docs/RAG_SETUP.md)
- [Real-Time Video](docs/REALTIME_SETUP.md)
- [Security Boundaries](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Competition Evaluation](docs/BENCHMARK.md)

## Security and Data

By default, the LLM and vision HTTP services and the UI client allow only loopback addresses or explicitly approved local networks. File access is constrained by allowed roots, sensitive-file checks, and symbolic-link escape protection. Operations such as starting or stopping cameras, batch reads, and report writes may require user confirmation. Before running the system, review the permission configuration, model and dataset licenses, and any site-sensitive information in generated outputs.
