# Screen-AI — Project Specification Document

**Track 2: Agentic AI — AMD Radeon & ROCm Hackathon**
**Version 1.0 — 2026-08-06**

---

## 1. Application Scenarios

Screen-AI is a **fully local/offline PC operator AI**: a desktop agent that receives natural-language commands from a phone or PC, perceives the screen, plans a safe action sequence, and executes it with explicit user approval for anything risky.

| Scenario | Example command | Flow |
|----------|-----------------|------|
| Desktop control | "Open Excel, log in if needed, check my recent sheet" | Open app → detect login → vault unlock via phone → continue |
| Research & collect | "Research AMD ROCm and save a report to my folder" | Search → visit pages → extract text → save report |
| Screen automation | "Click Share" | Screenshot → UIA map + OCR + detector → click center → verify |
| File safety | "Delete everything in Downloads" | Scan → count impact → phone approval → quarantine (reversible) |
| Web tasks | "Search best air coolers in Chrome" | Open browser → search → return results |
| Password login | "Login to xyz.com" | Open site → detect login → phone unlock → fill → continue |
| Passkey login | "Sign in with passkey" | Trigger OS/browser passkey → phone/Windows approval → wait → continue |
| System status | "Check my PC" | Report CPU, RAM, disk, battery, processes |
| Compound command | "Open File Explorer, open Desktop, find x.file, open WhatsApp Web, attach the file and send it" | One chained execution plan with 8 steps |

**Primary users:** a PC owner who wants their own machine to be controllable by an AI agent — from the couch, from the phone — while keeping every critical decision on the phone for approval. No sensitive data leaves the machine.

## 2. Agent Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                      Mobile Remote (Phone)                       │
│  Command ▸ Approval ▸ Vault Unlock ▸ Emergency Stop ▸ History    │
└───────────────────────────────┬──────────────────────────────────┘
                                │ REST + WebSocket (paired, token-auth)
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Local PC Agent Server (FastAPI)                 │
│                                                                  │
│  ┌──────────────────────── Agent Router ─────────────────────┐  │
│  │  Command → Cognitive Planner → Risk → Permission → Plan  │  │
│  │           → Execution Graph → Tool → Verify → Respond     │  │
│  └──────────────────────────────────────────────────────────┘  │
│             │             │             │             │         │
│      ┌───────▼────┐ ┌─────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐ │
│      │  Planner   │ │  Risk /    │ │ Approval │ │  Memory /  │ │
│      │ (rule + LLM│ │ Permission │ │ Manager  │ │  Tracer    │ │
│      │  + graph)  │ │  Engine    │ │          │ │            │ │
│      └────────────┘ └────────────┘ └──────────┘ └────────────┘ │
│             │             │             │             │         │
│      ┌───────▼──────────────────────────▼──────────────▼──────┐ │
│      │  Tool Executor: file · system · browser · auth ·       │ │
│      │  download · screen · skill registry · task graph       │ │
│      └───────────────────────────────────────────────────────┘ │
│             │                                                  │
│      ┌───────▼───────────────────────────┐                     │
│      │  Perception (screen perception)   │                     │
│      │  UIA ▸ OCR ▸ YOLO INT8 ▸ OpenCV   │                     │
│      └───────────────────────────────────┘                     │
└───────────────────────────────┬────────────────────────────────┘
                                │ Windows UIA / OpenCV / PyAutoGUI / Playwright
                                ▼
                  ┌────────────────────────────┐
                  │   Windows PC (the target)  │
                  │  files · apps · browser ·  │
                  │  system · credentials      │
                  └────────────────────────────┘
```

**Cloud training side (disconnected from runtime):**

```
Screenshots → OmniParser v2 teacher (AMD ROCm GPU)
           → teacher labels → YOLO dataset
           → YOLOv8n student training (AMD ROCm GPU)
           → INT8 ONNX export → staged into laptop runtime
```

## 3. Core Capabilities

### 3.1 Agent Brain
- **Cognitive planner**: 60+ intents, 200+ site aliases, 98 app aliases, 126 synonyms, spelling correction, memory learning (`planner_memory.json`).
- **Compound command decomposition**: splits chained commands (`then`, `and`, `,`) into one multi-step execution plan with per-step pipeline/model/verification metadata.
- **Task planner**: research_collect, open_settings, keep_awake, browser_session, send_file (entity-driven FILE/CONTACT/CHANNEL).
- **External reasoning** (optional): DeepSeek-V4-Flash via AMD Radeon API for unknown intents; plans are advisory and validated against the allowed tool namespace. Key is env-var only, never logged.
- **Execution graph**: DAG executor with node types (observe, decide, act, verify, retry, rollback, checkpoint, approval, wait, replan, finish); auto-inserted approval nodes for risk ≥ 3.

### 3.2 Tool Execution
- File (list, read, move, quarantine, restore), System (status, disk, RAM, processes, open_app), Browser (open, search, click, type, download via Playwright with system-browser fallback), Auth (password login, passkey login), Download manager, Screen (scan, click_text).
- 50-skill MVP registry + DAG task executor + verification engine (8 verifiers) + memory engine + structured tracer.

### 3.3 Safety & Trust
- **Risk levels 0–5**: read-only → full access special mode.
- **Phone approval** for level 3+ (login, install, email) and level 4+ (delete, bulk, admin). Emergency stop always works.
- **Quarantine-first deletes** — permanent delete requires special approval.
- **Password vault**: AES-256-GCM + Argon2id, 5-minute unlock session, secrets redacted from logs/screenshots.
- **Pairing**: 6-digit code (fallback), QR X25519, trusted reconnect, token rotation.
- **Local-first**: no cloud dependency for the core runtime.

### 3.4 Screen Perception (the "eyes")
- Windows UI Automation element map (resident).
- PaddleOCR ONNX (det + rec) — fast text lane.
- YOLOv8n INT8 ONNX UI detector (button/input/checkbox/radio/dropdown/tab/menu/link/icon).
- OpenCV visual candidates; SSD-cold OmniParser teacher as explicit fallback only.

## 4. Model Introduction & Local Deployment Plan

| Model | Role | Format | Size | Where it runs |
|-------|------|--------|------|---------------|
| YOLOv8n (student) | UI element detector | INT8 ONNX | 3.2 MB | Laptop (ONNX Runtime) — lazy/warm |
| PaddleOCR det v3 | text box detection | ONNX | ~8 MB | Laptop (ONNX Runtime) — lazy/warm |
| PaddleOCR rec English | text recognition | ONNX | ~7.5 MB | Laptop (ONNX Runtime) — lazy/warm |
| Qwen2.5 Coder 1.5B Q4_0 | local planner/reasoner | GGUF (mmap) | ~1 GB | Laptop — SSD-cold, loaded only if RAM budget allows |
| OmniParser v2 icon detect | teacher icon detector | Ultralytics YOLO `m` | ~39 MB | Cloud GPU only (distillation / explicit fallback) |

**Local deployment (4 GB RAM laptop):**

- **Tier 0 — resident**: rules, UIA, OpenCV, native endpoint ranking. Always available, near-zero RAM cost.
- **Tier 1 — warm/lazy**: OCR + YOLO INT8 loaded only when a screen task needs them; evicted after idle.
- **Tier 2 — SSD-cold**: Qwen GGUF stays on disk, mmap-loaded for complex/unknown commands only.
- **Tier 3 — SSD-off**: OmniParser/teacher never resident on the laptop.

The runtime engine (`app/runtime/resource_budget.py`, `tier_manager.py`, `model_registry.py`) measures real RAM with psutil and enforces this budget automatically; env vars allow simulating a 4 GB profile.

## 5. Inference-Speed Optimization on AMD Radeon GPU (ROCm)

### 5.1 Verified benchmarks (2026-08-06, AMD Instinct MI300X 192 GB, ROCm 7.14)

| Workload | ROCm GPU | CPU | Speedup |
|----------|----------|-----|---------|
| 2048×2048 matmul | 96 TFLOPS | — | — |
| YOLOv8n UI detector inference (640×640) | **6.82 ms/frame (~147 fps)** | 20.93 ms/frame (~48 fps) | **3.1×** |
| Tiny CNN (screen-perception proxy) | 0.09 ms/frame | — | — |

### 5.2 Optimization techniques applied

1. **Model compression — INT8 quantization**: the student YOLOv8n is exported to INT8 ONNX (dynamic quantization), shrinking it to **3.2 MB** so a 4 GB laptop can hold it. INT8 also reduces bandwidth pressure on GPU inference.
2. **Teacher–student distillation**: heavy OmniParser v2 (39 MB, YOLO `m`) labels screenshots once on the cloud GPU; the laptop runs only the tiny student. Inference cost at the edge is minimized by design.
3. **RAM-aware tiered loading**: only the smallest models are resident; the rest are lazy/evicted — keeps a 4 GB machine usable and avoids GPU/memory thrash.
4. **GPU-accelerated training**: YOLOv8n training on the MI300X used ROCm-aware PyTorch (`torch 2.10.0+rocm7.0`, HIP backend); 30-epoch training on a 24-image UI dataset completes in seconds, proving the full cloud loop is ROCm-accelerated.
5. **Native fallbacks**: JS fallbacks in the pipeline mirror C++ accelerators (op-codes 0–133) so behavior is correct without the native addon, and fast when it is present.
6. **Streaming/async I/O**: FastAPI async endpoints, a shared SQLite connection in WAL mode, lazy Playwright (unloads Chromium after idle) — no blocking waits in the command path.

### 5.3 ROCm environment used

```bash
# AMD devcloud: rocm-7-14-software-gpu-mi300x1-192gb
rocm-smi            # ROCm 7.14, MI300X, 192 GB VRAM
python -m pip install --pre torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/rocm7.0
# torch 2.10.0+rocm7.0, hip_available=True,
# device = AMD Instinct MI300X VF
```

## 6. Tech Stack & Repository Layout

| Module | Path | Purpose |
|--------|------|---------|
| AI PC Operator | `ai_pc_operator/` | FastAPI server + agent brain + runtime engine + mobile remote |
| Screen Scanner | `screen_element_scanner/` | UIA + OpenCV screen perception |
| Distillation Pipeline | `hackathon_ui_operator_distill/` | Cloud teacher → student training → INT8 export |
| JS Pipeline | `pipeline/` | 17-phase planning/execution engine + 249 graph pipelines |

**Backend**: Python 3.10+, FastAPI, aiosqlite, psutil, Playwright, cryptography, PyAutoGUI
**Frontend**: Vanilla JS/CSS/HTML, WebSocket, QRCode.js
**ML/Training**: Ultralytics YOLOv8n, ONNX Runtime, llama.cpp, PaddleOCR
**Security**: AES-256-GCM, Argon2id, X25519, HMAC signatures
**Database**: SQLite (WAL, serialized access, indexed)

## 7. Verification Summary (from live cloud run)

- `rocm-smi`: AMD Instinct MI300X, 192 GB VRAM, ROCm 7.14.
- `torch.cuda.is_available()` = True with HIP backend; device reports `AMD Instinct MI300X VF`.
- OmniParser v2 teacher labeled 24 screenshots (456 icon detections) on the GPU.
- YOLOv8n student trained on the labeled dataset; best.pt reached **mAP50 0.492**.
- INT8 ONNX exported and staged into `ai_pc_operator/data/models/ui_detector_int8.onnx` (3.2 MB); laptop runtime inventory confirms discovery.
- Inference: **6.82 ms/frame on ROCm vs 20.93 ms/frame on CPU → 3.1× speedup**.
