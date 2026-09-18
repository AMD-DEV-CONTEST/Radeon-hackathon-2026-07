# BuildGuard-Radeon

An AI-powered construction site safety inspection system optimized for AMD Radeon/ROCm GPUs. It runs entirely on local hardware — no cloud required.

## What it does

Given images or video of a construction site, the system:
1. Detects safety violations (missing helmets, vests, unsafe equipment positions) using computer vision
2. Scores the risk level of each violation
3. Looks up relevant safety regulations from a local knowledge base
4. Lets a safety inspector chat with an AI agent about the findings
5. Generates inspection reports (Markdown/HTML/PDF)

## Stack

- **API**: FastAPI (`buildguard serve-api` → port 8000)
- **UI**: Streamlit (`buildguard serve-ui` → port 8501)
- **Agent**: LangGraph state machine
- **Vision**: RT-DETRv2 (Vision Transformer object detector)
- **RAG**: Hybrid BM25 + embeddings over ingested safety documents
- **LLM**: Local inference via llama.cpp or vLLM, AMD ROCm backend
- **Storage**: SQLite + SQLAlchemy (conversation memory, inspection cache)

## Project layout

```
src/buildguard/
  api/          FastAPI routes (agent, RAG, vision, upload, cameras)
  agent/        LangGraph state machine + nodes + tools
  vision/       RT-DETRv2 detector, preprocessing, postprocessing
  risk/         Deterministic risk scoring
  rag/          Hybrid retrieval, query rewriting, answer grounding
  realtime/     Multi-camera management, adaptive frame sampling
  llm/          LLM backend abstraction (mock, llama-cpp, vLLM)
  reporting/    Report generation (Markdown, HTML, PDF)
  security/     Path guards, capability-based execution control
  storage/      SQLite schema, Alembic migrations, multi-turn memory
  monitoring/   ROCm/GPU metrics (rocm-smi, amd-smi)
  schemas/      Pydantic models for all entities
  cli.py        Typer CLI entry point (20+ subcommands)
  config.py     Settings loader (YAML-backed)

tests/          34 test files, 198 tests
configs/        Per-subsystem YAML configs
scripts/        Build, deploy, benchmark scripts
```

## Image input data flow

```
JPEG/PNG upload or image_path in agent chat
  │
  ▼
routes_upload.py — validate format, compute SHA256, persist to disk + DB
  │
  ▼
vision/preprocessing.py: decode_image()
  read bytes → SHA256 → cv2.imdecode → DecodedImage (BGR uint8 numpy array, H×W×3)
  │
  ▼
vision/preprocessing.py: letterbox()
  resize proportionally to 640×640, pad with gray (114,114,114) → keep LetterboxTransform
  │
  ▼
RTDetrImageProcessor (HuggingFace) — BGR→RGB, normalize, convert to float32 tensor (1×3×640×640)
  │
  ▼
RT-DETRv2 forward pass (Vision Transformer)
  backbone → spatial feature maps
  transformer decoder → N=300 raw candidates: scores (N,), labels (N,), boxes (N,4) in letterbox space
  │
  ▼
RTDETRv2Adapter._adapt()
  filter by confidence threshold (e.g. 0.35)
  map class ID → label string ("no-helmet", "no-vest", "person", ...)
  reverse letterbox transform → boxes in original image pixel coords
  │
  ▼
class_aware_nms() — greedy NMS per class (IoU threshold ~0.5), then multi-model fusion NMS
  │
  ▼
list[Detection]
  label: str          "no-helmet"
  confidence: float   0.91
  bounding_box:       x1, y1, x2, y2  (original image pixel coords)
  source_model: str   "rtdetr_v2"
```

## Risk scoring

Takes `list[Detection]` + `list[RetrievedEvidence]` (from RAG) and produces a `RiskAssessment`.

For each detection, six component scores are computed (all 0–1):

| Component | Weight | How computed |
|-----------|--------|--------------|
| severity  | 35%    | Label lookup table (e.g. "no-helmet" → 0.9) |
| location  | 20%    | Vertical position: top=0.8, middle=0.55, bottom=0.35 |
| confidence| 15%    | Detector confidence directly |
| evidence  | 10%    | Max RAG relevance score |
| duration  | 10%    | `min(seconds / 60, 1.0)` |
| frequency | 10%    | `log(1 + count) / log(6)`, clamped to 1.0 |

Combined: `score = 0.35×severity + 0.20×location + 0.15×confidence + 0.10×(evidence + duration + frequency)`

Score thresholds:
- `[0.00, 0.30)` → LOW
- `[0.30, 0.55)` → NORMAL
- `[0.55, 0.75)` → HIGH
- `[0.75, 1.00]` → CRITICAL

## RAG pipeline

Safety regulations, site manuals, and compliance documents (PDF/DOCX/MD/TXT) are ingested into a hybrid index. At query time, detection labels are used to search: `"construction safety standards + no-helmet + no-vest"`. Results feed into the evidence component of risk scoring and are cited in the final LLM response.

## Agent architecture

The agent is a LangGraph state machine. All state is a single `AgentState` TypedDict passed through nodes.

```
START
  → intent_classify       LLM: inspection / query / history / report, simple / multi_step
  → memory_retrieve       load last 8 messages for session
  → plan_generate         LLM: generate DAG of tool calls (JSON)
  → permission_check ─────────────────────────────────────────────┐
  → tool_execute          run tools in dependency order            │ confirmation required?
  → result_verify         LLM: did tools answer the question?      → wait_for_confirmation → END
      ├─ verified → response_generate   LLM: synthesize answer     │
      ├─ recoverable → replan ─────────────────────────────────────┘
      └─ failed → safe_failure
  → memory_save
  → END
```

The LLM never calls tools directly — it writes a plan, a separate executor runs it, a third LLM call verifies results. Three LLM calls per request.

Available tools: `inspect_image`, `inspect_image_batch`, `search_construction_standards`, `assess_risk`, `generate_inspection_report`, `get_session_history`, file tools, camera/realtime tools.

Key safety properties:
- All tool inputs carry trust labels (`TRUSTED_USER_INSTRUCTION`, `UNTRUSTED_TOOL_OUTPUT`, etc.) to block prompt injection
- Confirmation gate: tools like `inspect_image` require explicit user approval before running
- Replan loop: max 2 total attempts on recoverable failures
- Path guards and capability-based execution control on all file/tool access

## Server run commands (AMD GPU server)

All services run on the server at `/persistent/BuildGuard-Radeon-backup`. The repo has `scripts/start_all.sh` which starts llama-server → waits for LLM → starts API → starts UI → health checks all three. Override the `BG_*` env vars to match the actual server layout.

### Start everything (one command)
```bash
cd /persistent/BuildGuard-Radeon-backup
BG_PVC=/persistent/BuildGuard-Radeon-backup \
BG_REPO=/persistent/BuildGuard-Radeon-backup \
BG_VENV=/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721 \
  scripts/start_all.sh
```

### Stop everything
```bash
cd /persistent/BuildGuard-Radeon-backup
BG_PVC=/persistent/BuildGuard-Radeon-backup \
  scripts/stop_all.sh
```

### SSH tunnel (run on local machine)
```bash
ssh -L 18000:127.0.0.1:8000 -L 18501:127.0.0.1:8501 amd -N
```

### Browser access (after SSH tunnel)
- Swagger API docs: `http://localhost:18000/docs`
- Streamlit UI: `http://localhost:18501`

### Key paths on server
- llama-server: `runtime/llama.cpp/rocm-7.2.1/llama-b8407-.../llama-server` (auto-found by start_local_llm.sh)
- LLM model: `/persistent/BuildGuard-Radeon-backup/models/llm/qwen3-14b-q8/Qwen3-14B-Q8_0.gguf`
- Vision model: `models/vision/yolo11-ppe/yolo11m_safety.pt`
- Config: `configs/competition/app.yaml`
- Logs: `logs/` (llama-server.log, buildguard-api.log, buildguard-ui.log)
- Database: `workspace/database/buildguard.db`
- Uploads: `workspace/uploads/`
- RAG index: `workspace/indexes/construction_standards/`
- **Venv: `/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721`** — this is the ROCm-compatible venv with torch 2.9.1+rocm7.2.1. Do NOT use `.venv/` — it has CUDA torch and is incompatible.

## Development workflow

**All code changes happen locally. The AMD GPU server is the deployment target.**

```
edit code locally
  → commit + push (git push)
  → ssh amd "cd /persistent/BuildGuard-Radeon-backup && git pull"
  → restart services on server if needed
```

### Deploy and test cycle (step by step)

```bash
# 1. Commit and push locally
git add <files> && git commit -m "..." && git push

# 2. Pull on server
ssh amd "cd /persistent/BuildGuard-Radeon-backup && git pull"

# 3. Restart API (stop first if running)
ssh amd "BG_PVC=/persistent/BuildGuard-Radeon-backup \
  /persistent/BuildGuard-Radeon-backup/scripts/stop_api.sh"

ssh amd "BG_PVC=/persistent/BuildGuard-Radeon-backup \
  BG_REPO=/persistent/BuildGuard-Radeon-backup \
  BG_VENV=/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721 \
  /persistent/BuildGuard-Radeon-backup/scripts/start_api.sh"

# 4. Wait ~60 seconds for startup (models load slowly), then health check
ssh amd "for i in \$(seq 1 12); do sleep 5; \
  curl -sf http://127.0.0.1:8000/health && echo ' OK' && break \
  || echo \"attempt \$i: not ready\"; done"

# 5. End-to-end chat API test with an image
ssh amd "curl -s -X POST http://127.0.0.1:8000/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{\"message\": \"请检查这张图片的安全隐患\", \
       \"action\": \"inspect\", \
       \"image_paths\": [\"/persistent/BuildGuard-Radeon-backup/workspace/uploads/image1.png\"]}'"
```

**Important:** The API takes ~60 seconds to start (vision models + RAG index load). Do not assume failure after a few seconds — always poll health with a retry loop before testing.

- Local repo: `/home/isaber/BuildGuard-Radeon-backup`
- Server repo: `/persistent/BuildGuard-Radeon-backup` (connect via `ssh amd`)
- Server venv: `/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721` — always pass as `BG_VENV`, never use `.venv/`
- **Never edit files directly on the server** — always push via git.
- **Model files are downloaded on the server**, not locally. Use `ssh amd "curl ..."`.
- **Tests, linting, and type checking run on the server** — local machine has no Python env.
  - Run tests: `ssh amd "cd /persistent/BuildGuard-Radeon-backup && git pull && BG_VENV=/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721 envs/app-py312-rocm721/bin/pytest tests/ -q"`
  - Run ruff: `ssh amd "cd /persistent/BuildGuard-Radeon-backup && /root/.local/bin/uv run --python envs/app-py312-rocm721/bin/python ruff check src tests"`
  - Run mypy: `ssh amd "cd /persistent/BuildGuard-Radeon-backup && /root/.local/bin/uv run --python envs/app-py312-rocm721/bin/python mypy src"`
  - Server `uv` binary: `/root/.local/bin/uv` (add to PATH or use full path)
- HuggingFace mirror for China: `https://hf-mirror.com` (use instead of `huggingface.co`)
- PyPI mirror for China: `https://pypi.tuna.tsinghua.edu.cn/simple`

## Current status

All implementation complete. Deployed and running on AMD GPU server.

- AMD GPU: Radeon RX 7900 XTX, ROCm 7.2.1, gfx1100
- LLM: Qwen3-14B Q8 via llama.cpp ROCm build (~28 tok/s)
- Vision: YOLO11-PPE (`yolo11m_safety.pt`, confidence_threshold=0.35, device=cpu — torchvision in venv has no ROCm NMS kernel)
- RAG: 481 chunks indexed with Qwen3-embedding-0.6b (1024-dim)
- Venv: `envs/app-py312-rocm721` with torch 2.9.1+rocm7.2.1, transformers 4.51.3, torchvision 0.24.1 (CPU-only NMS)
