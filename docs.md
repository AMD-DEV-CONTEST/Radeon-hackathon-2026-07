# BuildGuard-Radeon — Project Documentation

## Application Scenarios

BuildGuard-Radeon is an AI-powered construction site safety inspection system that runs **entirely on local hardware** with no cloud dependency. It targets AMD Radeon GPU deployments (ROCm 7.2.1, tested on RX 7900 XTX / gfx1100).

### What it detects

| Defect / Violation | Base Severity | Notes |
|--------------------|--------------|-------|
| `unsafe_edge` | 0.90 | Unguarded drop edges |
| `exposed_wiring` | 0.85 | Live electrical hazard |
| `steel_corrosion` | 0.85 | Structural steel rust |
| `damage_severe` | 0.90 | Critical structural damage |
| `damage_moderate` | 0.65 | Moderate structural damage |
| `concrete_crack` | 0.75 | Crack propagation |
| `missing_helmet` | 0.75 | PPE violation |
| `damage_minor` | 0.40 | Minor surface damage |
| `missing_vest`, `person`, `guardrail`, `concrete_spalling`, `concrete_honeycomb` | 0.50 (default) | |

### Supported input types

- Single JPEG/PNG image (upload or local path)
- Batch of up to 50 images
- Video file (`.mp4`, `.avi`, `.mov`, `.mkv`) — sampled at configurable frame intervals
- Live camera streams (RTSP, USB, local video file loop)

### End-to-end workflow

1. User uploads image(s) / video or connects a camera stream
2. Vision pipeline detects defects and PPE violations (YOLO11, damage models)
3. MobileCLIP2 semantic router picks which specialist models to run per region-of-interest
4. RAG pipeline retrieves relevant safety regulation excerpts
5. Deterministic risk scorer produces `LOW / NORMAL / HIGH / CRITICAL` verdict per detection
6. AI agent synthesises a Chinese-language safety report with citations and recommended actions
7. Report exported to Markdown, HTML, or PDF

---

## Agent Architecture

The agent is a **LangGraph state machine**. The LLM never calls tools directly — it writes a JSON plan, a separate executor runs it, and a third LLM call verifies results. All state flows through a single `AgentState` TypedDict.

```
START
  │
  ▼
intent_classify ──────────────── categorise: inspection / query / history / report
  │                               complexity: simple / multi_step
  ▼
memory_retrieve ─────────────── load last 8 messages for session
  │
  ▼
plan_generate ───────────────── LLM writes a DAG of ≤6 tool-call steps (JSON)
  │
  ▼
permission_check ────────────── evaluate confirmation requirements
  │                               ┌──────────────────────────────────────────┐
  ├─ confirmation required ───────► wait_for_confirmation ──────────────────► END
  │
  ▼
tool_execute ────────────────── run each plan step in dependency order
  │                               trust-labelled inputs, bounded timeouts
  │
  ▼  [if visual phase]
inspection_analyze ─────────── LLM decides whether evidence / history lookups needed
  │
  ▼  [if enrichment phase]
risk_plan ───────────────────── build deterministic risk-scoring step
  │
  ▼
result_verify ───────────────── LLM validates outputs
  │
  ├─ verified ─────────────────► response_generate ──── LLM synthesises answer
  │                                                       with answer grounding
  ├─ recoverable (≤1 replan) ──► replan ────────────────► back to tool_execute
  │
  └─ failed ───────────────────► safe_failure
  │
  ▼
memory_save ─────────────────── persist to SQLite
  │
  ▼
END
```

### Graph nodes

| Node | File | Key function |
|------|------|-------------|
| `intent_classify` | `agent/nodes/intent.py` | `classify_intent()` |
| `memory_retrieve` | `agent/nodes/memory.py` | `retrieve_memory()` |
| `plan_generate` | `agent/nodes/planner.py` | `generate_plan()` |
| `permission_check` | `agent/nodes/permission.py` | `check_permission()` |
| `tool_execute` | `agent/nodes/executor.py` | `execute_tools()` |
| `inspection_analyze` | `agent/nodes/inspection_analysis.py` | `analyze_inspection()` |
| `risk_plan` | `agent/nodes/inspection_analysis.py` | `build_risk_plan()` |
| `result_verify` | `agent/nodes/verifier.py` | `verify_result()` |
| `replan` | `agent/nodes/replan.py` | `replan()` |
| `response_generate` | `agent/nodes/response.py` | `generate_response()` |
| `memory_save` | `agent/nodes/memory_save.py` | `save_memory()` |
| `safe_failure` | `agent/nodes/response.py` | `safe_failure()` |
| `wait_for_confirmation` | `agent/nodes/response.py` | `wait_for_confirmation()` |

### Key safety properties

- **Trust labels** — every tool input carries a provenance tag (`TRUSTED_USER_INSTRUCTION`, `UNTRUSTED_TOOL_OUTPUT`, …) to block prompt-injection attacks
- **Confirmation gate** — batch inspection, video inspection, and report generation require explicit user approval before execution
- **Replan cap** — maximum 1 retry on recoverable failures (`max_replans: 1`)
- **Path guards** — `PathGuard` enforces filesystem allowlists at both the capability-token layer and inside each tool handler
- **Control plan freezer** — tool plan is cryptographically frozen before execution; bindings are verified per-step

### Registered agent tools

| Tool | Requires confirmation |
|------|-----------------------|
| `inspect_single_image` | no |
| `inspect_image_batch` | yes |
| `inspect_image_batch_structured` | yes |
| `inspect_video` | yes |
| `inspect_conditionally` | no |
| `search_construction_standards` | no |
| `assess_risk` | no |
| `generate_inspection_report` | yes |
| `generate_event_report` | yes |
| `query_task_history` | no |
| `start_camera_monitoring` | yes |
| `stop_camera_monitoring` | no |
| `query_recent_events` | no |

---

## Core Capabilities

### 1. Vision inspection (`src/buildguard/vision/`)

`VisionInspectionService` coordinates all model inference through a `ConditionalVisionPipeline`. Admission control is enforced by `GpuInferenceGate`.

**Image path:** decode → letterbox to 640×640 → model forward pass → class-aware NMS → `list[Detection]`

**Video path:** `cv2.VideoCapture` frame sampling at configurable intervals → per-frame `inspect_single()` → aggregated `VideoInspectionOutput` with frame timestamps

**Deduplication:** each result carries a 64-char SHA256 `evidence_id`

**Confidence threshold:** 0.35 — detections below this are discarded  
**Requires-review threshold:** 0.65 — triggers mandatory human review flag

### 2. Risk scoring (`src/buildguard/risk/`)

Entirely deterministic — no LLM involved. `RiskAssessmentService` computes six component scores per detection:

| Component | Weight | Method |
|-----------|--------|--------|
| severity | 35% | Label lookup table |
| location | 20% | Y-position: top=0.80, mid=0.55, bot=0.35 |
| confidence | 15% | Detector confidence directly |
| evidence | 10% | Max RAG relevance score (default 0.20) |
| duration | 10% | `min(seconds / 60, 1.0)` |
| frequency | 10% | `log(1 + count) / log(6)`, clamped 1.0 |

Final score thresholds: `[0.00, 0.30)` LOW · `[0.30, 0.55)` NORMAL · `[0.55, 0.75)` HIGH · `[0.75, 1.00]` CRITICAL

Output includes the `governing_detection` (highest-risk), Chinese `summary`, and `recommended_actions`.

### 3. RAG pipeline (`src/buildguard/rag/`)

Hybrid BM25 + dense retrieval over ingested safety documents (PDF, DOCX, Markdown, plain text).

| Parameter | Value |
|-----------|-------|
| Embedding model | Qwen3-embedding-0.6b (1024-dim, local) |
| Reranker | Qwen3-reranker-0.6b (local) |
| Chunk size | 300–700 chars, 60-char overlap |
| BM25 top-k | 20 |
| Dense top-k | 20 |
| Fusion top-k | 15 |
| Final top-k (after rerank) | 5 |
| Answer grounding min coverage | 0.25 |
| Advanced RAG | enabled — LLM gate + query rewriter |

Ingest via API (`POST /rag/ingest`) or CLI (`buildguard ingest-docs`). Supported file types: `.pdf`, `.docx`, `.md`, `.txt` (max 50 MB per file, 100 MB per batch).

### 4. Realtime camera monitoring (`src/buildguard/realtime/`)

`CameraManager` coordinates multi-camera streams. Supported sources: RTSP, USB, local video file loop.

Key components:
- `AdaptiveMotionSampler` — drops duplicate frames to save GPU cycles
- `ByteTrackTracker` / `ObservationCentricByteTrackTracker` — multi-object tracking across frames
- `MOfNConfirmation` — temporal confirmation (M-of-N pattern) to suppress false alarms
- `PPEEventDetector` — emits events when safety violations persist for N frames
- `EventEngine` with `DatabaseRealtimeStore` — persists events to SQLite with clip paths

### 5. Report generation (`src/buildguard/reporting/`)

`ReportBuilder` accepts structured inspection findings and produces Markdown → HTML → optional PDF.

- Citations validated against RAG chunks with `CitationValidator`
- Chinese language throughout
- Default human-review footer: _"待现场授权人员复核并签字。"_
- `generate_event_report` tool packages realtime camera events into the same format

### 6. LLM backend (`src/buildguard/llm/`)

Abstraction layer with three backends: `MockLLMBackend` (deterministic, no GPU), `OpenAICompatibleLocalBackend` (llama.cpp / vLLM via HTTP), future API backend.

Generation profiles:

| Profile | Thinking | Temperature | Max tokens |
|---------|----------|-------------|-----------|
| `structured_plan` | off | 0.2 | 768 |
| `normal_dialogue` | off | 0.7 | 768 |
| `complex_replan` | on | 0.6 | 1200 |

---

## Model Introduction & Local Deployment

### Deployed model stack

| Role | Model | Format | Path on server |
|------|-------|--------|----------------|
| LLM | Qwen3-14B-Q8 | GGUF (8-bit) | `models/llm/qwen3-14b-q8/Qwen3-14B-Q8_0.gguf` |
| Embedding | Qwen3-embedding-0.6b | HuggingFace | `models/embedding/qwen3-embedding-0.6b` |
| Reranker | Qwen3-reranker-0.6b | HuggingFace | `models/reranker/qwen3-reranker-0.6b` |
| PPE detection | YOLO11m-Safety | PT | `models/vision/yolo11-ppe/yolo11m_safety.pt` |
| Crack segmentation | YOLOv8-crack-seg | PT | `models/vision/yolov8-crack-seg/best.pt` |
| Damage severity | Kompon-damage-severity | PT | `models/vision/kompon-damage-severity/best.pt` |
| Corrosion detection | YOLOv-corrosion | PT | `models/vision/yolov-corrosion/best.pt` |
| Semantic router | MobileCLIP2-S0 | PT | `models/vision/mobileclip2-s0/mobileclip2_s0.pt` |

### Vision model class mappings

| Model | Raw class → internal label |
|-------|---------------------------|
| YOLO11-PPE | `nohat` → `missing_helmet`, `novest` → `missing_vest`, `person` |
| YOLOv8-crack-seg | `crack` → `concrete_crack` |
| Kompon-damage | `microcrack/structural_crack/spalling` → `damage_moderate`, `rebar_corrosion` → `steel_corrosion`, `severe_distress` → `damage_severe` |
| YOLOv-corrosion | `Rust` → `damage_minor`, corrosion variants → `steel_corrosion` |

### Semantic router — MobileCLIP2-S0

MobileCLIP2-S0 is a lightweight vision-language model (CLIP-family) used as a routing layer before running specialist detectors. It classifies each region-of-interest using positive/negative text prompts and routes to the appropriate detector(s).

| Parameter | Value |
|-----------|-------|
| Device | CUDA (fp16) |
| Semantic weight | 0.70 |
| Temperature | 0.07 |
| Cache | 256 items LRU |
| Estimated VRAM | 512 MB |

**Why MobileCLIP2 instead of running all detectors:** Running YOLO11 + crack-seg + damage + corrosion on every frame is both slow and noisy. The semantic router acts as a fast pre-filter, spending GPU only on the detector most likely to fire for the content in frame — reducing inference latency and false positives.

### Local deployment (AMD GPU server)

**Requirements:** AMD Radeon RX 7900 XTX or similar RDNA3/RDNA2 GPU, ROCm 7.2.1, Python 3.12, PyTorch 2.9.1+rocm7.2.1

```bash
# Start all services (llama-server → API → UI)
cd /persistent/BuildGuard-Radeon-backup
BG_PVC=/persistent/BuildGuard-Radeon-backup \
BG_REPO=/persistent/BuildGuard-Radeon-backup \
BG_VENV=/persistent/BuildGuard-Radeon-backup/envs/app-py312-rocm721 \
  scripts/start_all.sh

# SSH tunnel (from local machine)
ssh -L 18000:127.0.0.1:8000 -L 18501:127.0.0.1:8501 amd -N

# Access
# Swagger API: http://localhost:18000/docs
# Streamlit UI: http://localhost:18501
```

**Notes:**
- Use venv `envs/app-py312-rocm721` — do **not** use `.venv/` (has CUDA PyTorch, incompatible)
- API startup takes ~60 seconds (vision models + RAG index load)
- LLM throughput: ~28 tok/s on RX 7900 XTX
- Vision models run on CPU (torchvision in venv has no ROCm NMS kernel); LLM and embedding on GPU

---

## AMD Radeon Optimization Details

### GPU scheduler (`src/buildguard/scheduling/`)

`GpuScheduler` implements priority-based task queuing with deadline awareness:

| Task type | Priority use case |
|-----------|------------------|
| `emergency_vision` | Highest — realtime safety alerts |
| `risk_confirmation` | Fast-track risk scoring |
| `normal_monitoring` | Standard camera frame processing |
| `agent_response` | Interactive chat inference |
| `report_generation` | Background report build |
| `background_indexing` | RAG index updates |

Unload strategy: evicts the largest non-pinned models first to free VRAM for incoming tasks.

### GPU admission gate (`GpuInferenceGate`)

Thread-safe contextmanager used by every model call:

```python
with gpu_gate.acquire(task):
    model.inference(...)
```

- Polls every 50ms, wait timeout 30 seconds
- Bypasses gate gracefully if telemetry is unavailable (fault-tolerant degraded mode)
- Tracks `active_inference` count for back-pressure

### Hardware telemetry (`src/buildguard/monitoring/`)

`CompositeMonitor` tries `AmdSmiMonitor` (newer `amd-smi metric --json`) then falls back to `RocmSmiMonitor` (`rocm-smi --showallinfo --json`). Both parse:

- GPU utilization (`gfx_activity` / `gpu_use`)
- VRAM used / total
- Temperature, power draw

Telemetry feeds `MonitoredGpuResourceProvider` → `GpuInferenceGate` → scheduler decisions.

### Model residency registry (`ModelResidencyRegistry`)

Tracks which models are loaded into GPU memory process-wide. Pin a model to prevent the unload strategy from evicting it. Used by `create_app()` to pre-register all enabled models at startup:

```python
residency.register("vision:yolo11-ppe", 2048)        # MB
residency.register("vision-router:mobileclip2-s0", 512)
residency.register("llm:qwen3-14b", 14000)
residency.register("embedding:qwen3-embedding-0.6b", 1200)
```

### ROCm-specific build notes

- `torch 2.9.1+rocm7.2.1` from AMD ROCm PyPI channel
- `torchvision 0.24.1` (CPU NMS — ROCm torchvision NMS kernel not yet available in this build)
- llama.cpp compiled with `LLAMA_HIP=1` for ROCm, `gfx1100` target
- HuggingFace downloads use mirror `https://hf-mirror.com` for deployments in China

---

## API Reference

Base URL: `http://localhost:8000` (or `:18000` through SSH tunnel)

### Agent

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agent/chat` | Submit a query; returns SSE stream or JSON response |
| `POST` | `/agent/confirm` | Approve a pending tool confirmation |

`POST /agent/chat` body:
```json
{
  "message": "请检查图片中的安全隐患",
  "session_id": "optional-uuid",
  "action": "inspect",
  "image_paths": ["/workspace/uploads/site.jpg"]
}
```

### RAG

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/rag/ingest` | Ingest a document into the knowledge base |
| `POST` | `/rag/query` | Search safety regulations |
| `DELETE` | `/rag/remove` | Remove a document |
| `POST` | `/rag/ground` | Validate answer citations |

### Upload

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload/images` | Upload up to 20 images (≤20 MB each, ≤100 MB total) |

### Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mvp/performance` | GPU metrics + camera stats dashboard |
| `POST` | `/mvp/cameras/{id}/start` | Start camera monitoring |
| `POST` | `/mvp/cameras/{id}/stop` | Stop camera monitoring |
| `GET` | `/mvp/events` | Query recent realtime events |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check (LLM, DB, semantic router) |
| `GET` | `/runtime-mode` | Current runtime mode |
| `POST` | `/runtime-mode/enter/{mode}` | Switch mode (online/indexing/training) |

---

## CLI Reference

```
buildguard --help

Commands:
  serve-api           Start the FastAPI server (default port 8000)
  serve-ui            Start the Streamlit UI (default port 8501)
  validate-config     Parse and print redacted config (--config configs/app.yaml)
  probe-environment   Report ROCm tools, GPU, LLM endpoint status
  benchmark-llm       Throughput benchmark for the configured LLM
  ingest-docs         Ingest documents into the RAG knowledge base
  competition-check   Readiness check (--level agent|rag|vision|full)
  runtime-mode        Subcommands to manage mutually exclusive runtime modes
```

---

## Project Structure

```
src/buildguard/
  api/              FastAPI routes (agent, RAG, vision, upload, cameras)
  agent/            LangGraph state machine + 13 nodes + production tools
    nodes/          intent, memory, planner, executor, verifier, response, …
  vision/           RT-DETRv2 / YOLO11 detectors, preprocessing, service
    routing/        Semantic router (MobileCLIP2) + Bayesian model selector
  risk/             Deterministic risk scorer (no LLM)
  rag/              BM25 + dense hybrid retrieval, query rewriter, grounding
    advanced/       Corrective retrieval, answer grounding with citations
  realtime/         Multi-camera manager, adaptive sampler, event engine
  reporting/        Markdown/HTML/PDF builder with Chinese language support
  llm/              Backend abstraction (mock, llama-cpp, vLLM)
  monitoring/       ROCm/amd-smi telemetry, performance dashboard
  scheduling/       GPU scheduler, admission gate, residency registry
  security/         PathGuard, capability tokens, taint tracking
  storage/          SQLite schema, Alembic migrations, long-term memory
  workspace/        Upload management, retention cleaner
  schemas/          Shared Pydantic models
  config.py         YAML-backed settings loader
  cli.py            Typer CLI entry point

tests/              37 test files, ~7800 lines
configs/            11 YAML config files
  competition/      Production overrides for server deployment
scripts/            start_all.sh, stop_all.sh, deploy helpers
docs/               Design specs and implementation plans
```
