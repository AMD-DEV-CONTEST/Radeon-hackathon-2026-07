# Screen-AI
demo video
https://drive.google.com/file/d/1WvqakA_qPcAKQae3T1FI90Yhym89vpM2/view?usp=sharing

**A fully local/offline PC operator AI, controlled by your PC and phone.**

Screen-AI is a local agentic desktop operator accelerated by AMD ROCm for screen perception, model distillation, and lightweight inference. You type a command on your phone (or PC); the agent perceives the screen, plans a safe action sequence, and executes it — with phone approval required for anything risky.

- **Track**: Track 2 — Agentic AI (AMD Radeon & ROCm hackathon)
- **Philosophy**: My PC · My phone · My AI · My approval · Full local control

> Full project specification: [`PROJECT_SPEC.md`](./PROJECT_SPEC.md)

---

## Feature Highlights

- 📱 **Mobile Remote Control** — send text commands from your phone; approve risky actions inline
- 👁️ **Screen Perception** — Windows UIA + OCR + YOLOv8n INT8 detector + OpenCV
- 🖱️ **Screen Control** — click elements by text, scan screen, verify the screen changed
- 🌐 **Browser Automation** — search, open sites, fill forms, download (Playwright, with system-browser fallback)
- 🔐 **Password Vault** — AES-256-GCM + Argon2id, 5-minute unlock sessions, redacted logs
- ✅ **Phone Approval** — risk level 3+ actions require mobile approval; emergency stop always works
- 📁 **File Quarantine** — delete → quarantine (reversible), never permanent by default
- 🤖 **Cognitive Planner** — 60+ intents, aliases, synonyms, memory learning, compound-command chaining
- 🧠 **Execution Graph** — DAG executor with auto-inserted approval nodes for risk ≥ 3
- 🧩 **Skill Registry** — 50-skill MVP pack, verification engine, task graphs, memory engine, tracer
- 📊 **RAM-Aware Runtime** — tiered model loading designed for 4 GB laptops
- 🌐 **External Reasoning** *(optional)* — DeepSeek-V4-Flash via AMD Radeon API for unknown intents
- 🎨 **Cloud Distillation** — OmniParser v2 teacher → YOLOv8n student → INT8 ONNX, trained on AMD ROCm

---

## Quick Start (Windows)

```powershell
# 1. Install backend dependencies
cd ai_pc_operator\backend
pip install -r requirements.txt

# 2. Install Playwright browser (for browser automation)
python -m playwright install chromium

# 3. Start the server
python -m app.main
```

Or launch everything with the bundled script:

```powershell
.\ai_pc_operator\start.bat
```

### Linux / Mac

```bash
./ai_pc_operator/start.sh
```

### HTTPS (for mobile QR camera pairing)

```powershell
python ai_pc_operator/backend/scripts/start_https.py
```

---

## Mobile Remote URLs

| URL | Purpose |
|-----|---------|
| `http://localhost:8000/remote/index.html` | Mobile remote (phone opens this) |
| `http://localhost:8000/remote/pair.html` | PC QR pairing page (PC shows this) |
| `https://localhost:8443/remote/...` | HTTPS variant (for camera QR scanning) |

From your phone, use `http://<pc-ip>:8000` on the same Wi-Fi.

---

## Model Artifacts

Download the local models:

```powershell
python ai_pc_operator/backend/scripts/download_models.py          # all artifacts
python ai_pc_operator/backend/scripts/download_models.py --skip-llm  # skip the 1 GB Qwen GGUF
```

Inspect the staged inventory:

```powershell
python ai_pc_operator/backend/scripts/model_artifacts.py inventory
python ai_pc_operator/backend/scripts/model_artifacts.py list-files
python ai_pc_operator/backend/scripts/model_artifacts.py stage-yolo .\path\to\ui_detector_int8.onnx
python ai_pc_operator/backend/scripts/model_artifacts.py stage-gguf .\path\to\qwen.gguf
```

Model files are never committed to git (`.gitignore` excludes `*.gguf`, `*.onnx`, `*.pt`).

---

## Environment Configuration

The runtime is RAM-aware and tunable via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCREEN_AI_RAM_MB` | *(measured)* | Simulate a RAM budget, e.g. `1200` for a 4 GB laptop |
| `SCREEN_AI_MMAP` | `1` | Memory-map GGUF files through llama.cpp |
| `SCREEN_AI_PREFETCH` | `0` | Disable model prefetch (safest for low RAM) |
| `SCREEN_AI_ALLOW_COLD_LLM` | `0` | Keep the local LLM on SSD unless explicitly enabled |
| `SCREEN_AI_LLM_CTX` | `512` | Small context window for the local planner |
| `SCREEN_AI_LLM_THREADS` | `2` | Limited CPU threads for the local planner |
| `SCREEN_AI_MODEL_DIR` | *(defaults)* | Extra folder to search for model artifacts |
| `SCREEN_AI_DB_PATH` | `data/agent.db` | Override the SQLite database path (tests use a temp file) |
| `SCREEN_AI_EXTERNAL_API_KEY` | *(unset)* | API key for optional external reasoning (env-var only, never logged) |
| `SCREEN_AI_EXTERNAL_BASE_URL` | `https://developer.amd.com.cn/radeon/api/v1` | OpenAI-compatible endpoint for external reasoning |
| `SCREEN_AI_EXTERNAL_MODEL` | `DeepSeek-V4-Flash` | Model name for external reasoning |

Example — simulate a 4 GB laptop profile:

```powershell
$env:SCREEN_AI_RAM_MB="1200"
$env:SCREEN_AI_PREFETCH="0"
$env:SCREEN_AI_ALLOW_COLD_LLM="0"
python -m app.main
```

---

## Cloud GPU Pipeline (AMD ROCm)

The teacher/student distillation pipeline trains a tiny UI detector on an AMD Radeon/ROCm GPU and exports an INT8 ONNX for the laptop.

```bash
cd hackathon_ui_operator_distill

# 1. Teacher labeling — OmniParser v2 on the GPU
python cloud/run_teacher_labeling.py \
  --screens data/raw_screenshots \
  --out data/labels_teacher \
  --weights ../ai_pc_operator/data/models/teachers/omniparser_v2_icon_detect.pt \
  --mode omniparser

# 2. Convert teacher labels to YOLO format
python cloud/convert_teacher_to_yolo.py \
  --labels data/labels_teacher --out data/yolo_dataset

# 3. Train the tiny student (ROCm device 0)
python cloud/train_student_yolo.py \
  --data data/yolo_dataset/ui_dataset.yaml \
  --model yolov8n.pt --epochs 80 --device 0

# 4. Export INT8 ONNX and stage it into the laptop runtime
python cloud/export_int8_onnx.py \
  --weights runs/ui_student/weights/best.pt \
  --out ui_detector_int8.onnx \
  --stage ../ai_pc_operator/data/models/ui_detector_int8.onnx
```

ROCm environment on the AMD devcloud:

```bash
python -m pip install --pre torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/rocm7.0
pip install ultralytics onnx onnxruntime pillow numpy pyyaml tqdm huggingface_hub
```

Verified on **AMD Instinct MI300X 192 GB / ROCm 7.14** (2026-08-06):

- `torch 2.10.0+rocm7.0`, `hip_available=True`, device `AMD Instinct MI300X VF`
- 2048×2048 matmul: **96 TFLOPS**
- YOLOv8n inference: **6.82 ms/frame on ROCm** vs 20.93 ms/frame on CPU → **3.1× speedup**
- Teacher labeling, student training (mAP50 0.492), and INT8 export all completed on the GPU

---

## Repository Layout

```
ai_pc_operator/
  backend/
    app/
      main.py               # FastAPI entry point
      agent/                # planner, router, task_planner, task_graph, memory_engine, prompts
      security/             # risk, permissions, pairing, vault
      approvals/            # approval manager
      tools/                # file, system, browser, download, auth, screen tools
      skills/               # skill registry, verification, runtime, MVP pack
      runtime/              # resource budget, model registry, tier manager, io pool
      observability/        # tracer
      db/                   # database, models
      logs/                 # redactor
  frontend/                 # React shell
  data/                     # agent.db, models/, quarantine/, downloads/
  docs/                     # architecture, permissions, vault, roadmap
  remote/                   # mobile web remote (HTML/JS)

screen_element_scanner/     # UIA + OpenCV screen perception ("the eyes")

hackathon_ui_operator_distill/
  cloud/                    # teacher labeling, YOLO training, INT8 export
  local_runtime/            # click_by_text, collect_screenshot
  data/                     # raw_screenshots/, labels_teacher/, yolo_dataset/
  native/                   # C++ accelerators (screenai_core, verifier_bridge)

pipeline/                   # 17-phase planning engine + 249 graph pipelines (JS)
  cli.js                    # node pipeline/cli.js agent "open chrome" --dry-run
```

---

## Dependencies

### Backend (`ai_pc_operator/backend/requirements.txt`)

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.104.1 | REST API framework |
| `uvicorn[standard]` | 0.24.0 | ASGI server |
| `pydantic` | 2.5.0 | Validation |
| `aiosqlite` | 0.19.0 | Async SQLite |
| `psutil` | 5.9.6 | System metrics |
| `playwright` | 1.54.0 | Browser automation |
| `cryptography` | 41.0.7 | AES-256-GCM, Argon2id |
| `pyautogui` | 0.9.54 | Mouse/keyboard control (Windows) |
| `opencv-python` | 4.8.1.78 | Vision |
| `numpy` | 1.26.2 | Arrays |
| `pillow` | 10.1.0 | Imaging |
| `onnxruntime` | 1.18.1 | Local model inference |
| `llama-cpp-python` | 0.2.90 | GGUF local LLM (optional) |
| `requests` / `aiohttp` | 2.31.0 / 3.9.1 | HTTP |
| `websockets` | 12.0 | WebSocket |
| `python-multipart` | 0.0.6 | Form parsing |

### Training / Cloud (`hackathon_ui_operator_distill/cloud/setup_cloud_gpu.sh`)

`ultralytics`, `onnx`, `onnxruntime`, `onnxruntime-tools`, `opencv-python`, `pillow`, `numpy`, `pyyaml`, `tqdm`, `huggingface_hub` — plus ROCm PyTorch from the official ROCm wheel index.

### Frontend

Vanilla HTML/CSS/JS + WebSocket + QRCode.js — no build step required.

---

## Testing

```powershell
# Backend smoke tests (run from ai_pc_operator\backend)
python -u test_basic.py
python -u test_new_spec.py
python -u test_login_v2.py
python -u test_cognitive_planner.py
python -u test_v2_external_chat_camera.py
python -u test_task_execution_policy.py
python -u test_generic_task_decomposition.py
python -u test_compound_sequence.py

# JS pipeline tests (run from repo root)
node pipeline/test_pipeline.js
```

---

## Safety & Boundaries

- Critical actions (delete, installers, email, credentials, passkey, admin commands) require phone approval.
- Passwords are redacted/deleted from logs; screenshots around password entry are blocked/redacted.
- Destructive operations use **quarantine first** — permanent delete needs special approval.
- Emergency stop always works; all non-secret actions are logged.
- This project automates the owner's own machine in a visible, approved session. It implements no stealth, bot-evasion, credential-theft, or hidden-control behavior.

## Contributors

- Nameera19
- madhavabrightly

## License

See the repository for license details. Contact: `madhavabrightly/Screen-AI`.
