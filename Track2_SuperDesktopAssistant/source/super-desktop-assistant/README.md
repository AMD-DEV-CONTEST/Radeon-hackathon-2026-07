# Super Desktop Assistant

> A multi-model intelligent scheduling desktop assistant — one chat interface that schedules multimodal LLMs in parallel to complete complex tasks.
>
> Entry for the **AMD AI DevMaster Hackathon · Track 2: Private AI Agents** — fully local on AMD Radeon (ROCm).

Users issue commands by **text or voice**; the system automatically:
**understands intent → generates a task DAG → routes to domain foremen → parallel-schedules multimodal LLMs / TTS / STT / image generation → returns results.**

---

## ✨ Features

| Capability | Description |
|---|---|
| 💬 **LLM reasoning** | Q&A, writing, translation, code generation (up to 8 tool-call rounds) |
| 👁️ **Vision analysis** | Image recognition, screenshot analysis, analyzing agent-generated images |
| 🎤 **STT** | Speech-to-text (OpenAI-compatible → local faster-whisper degradation) |
| 🔊 **TTS** | Text-to-speech (OpenAI-compatible → edge-tts → local HTTP) |
| 🎨 **Image generation** | ComfyUI (Qwen-Image) with API → SD-WebUI → ComfyUI degradation |
| 🔧 **Agent tools** | Function calling: read/write files, search code, generate images, shared memory |
| 🔀 **Multi-model scheduling** | Multi-provider parallel scheduling, capability routing, local-first |
| 💬 **Config via dialog** | Layer 1 (the only layer with config permission) adjusts models/params/paths in natural language |

**Agent tools** (8): `get_shared_memory`, `read_file` (PDF-aware), `write_file`, `search_code`, `list_files`, `generate_image`, `add_note`, `add_discovery`.

---

## ⚡ Design Highlights — *Rewrite → Activate → Maximize*

- **Real-time prompt rewriting**: before every node runs, plain commands are rewritten into expert-grade prompts (e.g. *"draw a silver-haired girl"* → `anime girl, silver long hair, very awa, masterpiece…`). The Planner structures the request, the prompt builder domain-optimizes it, and the Executor adjusts long-context prompts at runtime from upstream results.
- **Expert activation**: each task activates the best-fitting local expert — LLM / Vision → vLLM, Speech → Kokoro + whisper, Image → ComfyUI — orchestrated as a parallel task DAG.
- **Maximize local AI utilization**: local-first routing + DAG parallelism + ROCm-tuned vLLM (13.7 tok/s, +109% prefill) keep the AMD GPU fully busy and everything private.

---

## 🏗 Architecture (v3 — four layers)

```
User input (text / image / audio)
  │
  ▼
[L1] UserAgent      truncation · entity extraction · injection filter · config intercept
  ▼
[L2] Supervisor     Planner (LLM DAG) → Executor (topo-sort + parallel + retry) → Router
  ▼
[L3] Foremen        LLMForeman · SpeechForeman · ImageForeman (tool chains + degradation)
  ▼
[L4] MCP contract + multi-backend APIs (ai-coin unified access layer)
  ▼
[Memory] public_memory + task_memory
```

**Core flow**:
1. **Planner** (LLM) analyzes intent → outputs a JSON task DAG (nodes + dependencies).
2. **Executor** runs nodes in topological order, in parallel where possible; injects upstream outputs downstream; handles timeout/retry/failure propagation.
3. **Router** dispatches by node type: `llm / vision → LLMForeman`, `image_gen → ImageForeman`, `tts / stt → SpeechForeman`.
4. **Foremen** execute via `chat_with_tools` (ai-coin tool loop), falling back to plain chat if the model lacks function calling.

---

## 🚀 Quick Start

### 1. Environment

- Python 3.10+ (developed on 3.12)
- At least one LLM provider available. For fully local operation, run a local vLLM server (see below).

### 2. Local model services (recommended for this contest)

| Service | Command | Model |
|---|---|---|
| vLLM (LLM + vision) | `python -m vllm.entrypoints.openai.api_server --model <qwen2.5-vl-32b-awq> --port 8000 --max-model-len 36864 --enforce-eager` | Qwen2.5-VL-32B-AWQ |
| Audio API (TTS/STT) | `python audio_server.py` (OpenAI-compatible, port 8766) | Kokoro-82M + faster-whisper |
| ComfyUI (image) | `python main.py --listen 0.0.0.0 --port 8188 --gpu-only` | Qwen-Image |

### 3. Install & run

```bash
pip install -r requirements.txt
pip install PyPDF2 edge-tts        # optional
cp .env.example .env               # fill in at least one provider key

python app.py                      # CLI mode
python app.py --web                # Web UI (http://127.0.0.1:7860)
python app.py --window             # desktop window (optional)
python app.py --init-ai-coin       # one-time migration of config → ai-coin DB
```

> `--web` / `--window` must be explicit (Gradio / pywebview are lazy-loaded).

### 4. Programmatic API

```python
import asyncio
from src.main import get_engine

engine = get_engine()
result = asyncio.run(engine.process(
    user_message="your task description",
    conversation_history=[],
))
print(result["results"])
```

Returns: `{status, dag, plan_summary, results, errors, skipped, total_time_ms, outputs}`.

---

## ⚙️ Configuration

### `.env` (API keys — NOT committed)
| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `QWEN_API_KEY` / `ZHIPU_API_KEY` / `SILICONFLOW_API_KEY` / `MIMO_API_KEY` | cloud LLM providers |
| `VLLM_API_KEY` / `OLLAMA_API_KEY` | local inference (any value) |
| `SDWEBUI_URL` | SD-WebUI address (optional) |
| `LOCAL_TTS_URL` | local TTS endpoint (optional) |
| `GRADIO_SERVER_PORT` / `GRADIO_SHARE` | Web UI settings |

### `config.json` (non-API settings)
Providers/models are managed by **ai-coin** (`data/ai_coin.db` + `data/ai_coin_state.json`); `config.json` keeps only non-API settings (paths, execution timeouts, ComfyUI script, LLM defaults).

### In-dialog config (Layer 1 only)
```
"switch the LLM to deepseek"
"use openai gpt-4o for vision"
"set temperature to 0.7"
"prefer local ollama"
```

---

## 🧪 Tests

```bash
# Offline unit/regression (no real API)
python tests/test_quick.py
python tests/test_deep.py
python tests/test_v2.py
python tests/test_v3.py
python tests/test_regression_fixes.py
python tests/test_regression_refactor.py
python tests/test_ai_coin_bridge.py

# E2E (requires real LLM key)
python tests/run_chess_test.py
python tests/test_e2e_1.py          # visual novel generation (incl. ComfyUI)
python tests/test_e2e_2.py          # code review
python tests/test_e2e_3.py          # tetris
python tests/test_e2e_4.py          # PDF analysis
```

---

## 📦 Dependencies

```text
# Core
openai>=1.50.0
httpx>=0.27.0
python-dotenv>=1.0.0
ai-coin>=0.3.1
gradio>=4.0.0
pywebview>=4.0.0
loguru>=0.7.0
Pillow>=10.0.0

# Optional
faster-whisper     # local STT
edge-tts           # free TTS
PyPDF2             # PDF parsing
```

---

## 🚀 Deployment (Ubuntu 24)

```bash
chmod +x deploy-ubuntu24.sh && ./deploy-ubuntu24.sh   # installs systemd service, web mode
docker compose up -d                                  # Docker
```

---

## 📄 License

MIT
