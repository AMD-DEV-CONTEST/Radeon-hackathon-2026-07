# EduManim

**EduManim** is an AI-powered educational video generation platform. Given a topic or question, it automatically writes a narration script, synthesizes voiceover audio via text-to-speech, renders animated mathematical/educational visuals using [Manim](https://www.manim.community/), and assembles everything into a final MP4 video.

We had no time to record a video because I didn't know how I was supposed to download all the dependencies at 300 kB/s.

---

## Architecture Overview

```
EduManim/
├── backend/               # FastAPI REST + WebSocket API
│   ├── api.py             # Job queue, endpoints, WebSocket progress stream
│   └── agent/
│       ├── graph.py       # Sequential pipeline orchestrator
│       ├── state.py       # Shared pipeline state definition
│       └── nodes/         # Pipeline stages: scriptwriter, TTS, manim_coder, ffmpeg
├── frontend/
│   └── app.py             # Gradio web interface (port 7860)
├── LLM/
│   ├── llm.py             # LLM router (local / remote)
│   ├── llm_local.py       # llama-cpp-python backend (Qwen2.5-32B GGUF)
│   └── llm_remote.py      # OpenAI-compatible remote API backend
├── tools/
│   ├── manim/             # Manim scene renderer, validator, fallback, CLI
│   ├── rag/               # RAG pipeline (chunker, embeddings, retrieval, reranker)
│   ├── tts/               # Coqui TTS synthesis & audio cleaning
│   └── ffmpeg/            # Video assembly utilities
├── init.py                # Auto-downloads the LLM model on first run
├── requirements.txt       # Python dependencies
└── start.bash             # Single-command startup script
```

### Pipeline stages

1. **Scriptwriter** — LLM decomposes the user query into scenes (title, narration, visual hints)
2. **TTS** — Coqui TTS converts each scene's narration into an audio file
3. **Manim Coder** — LLM generates and validates Manim Python code for each scene; renders to video clips
4. **FFmpeg Assembler** — Merges audio + video clips into a single timestamped MP4

---

## Quick Start

> **The only command you need to run is:**
>
> ```bash
> bash start.bash
> ```

The script will:
1. Install system packages (build tools, Cairo, Pango, FFmpeg, LaTeX)
2. Install PyTorch 2.5.1 with ROCm 6.2 GPU support
3. Build and install `llama-cpp-python` with HIP/ROCm acceleration
4. Install all Python dependencies from `requirements.txt`
5. Auto-download the `Qwen2.5-32B-Instruct Q8_0` GGUF model from HuggingFace (first run only, ~34 GB)
6. Start the **FastAPI backend** on `http://localhost:8000`
7. Start the **Gradio frontend** on `http://localhost:7860`

Once everything is running, Gradio will print a **public link** directly in the terminal:

```
Running on local URL:  http://0.0.0.0:7860
Running on public URL: https://xxxxxxxxxxxxxxxx.gradio.live
```

Open the `gradio.live` URL from **any browser, anywhere** — no port-forwarding or VPN needed. The tunnel is created automatically via `share=True` in `frontend/app.py` and stays alive as long as the process is running.

> **Note:** The script targets a Linux/Debian environment (uses `apt-get`). It is intended to run inside a Docker container or a compatible Linux system.

---

## Environment Configuration

The project uses a `.env` file in the project root for configuration. Create it before running:

```bash
cp .env.example .env   # if an example file is provided, otherwise create manually
```

### `.env` variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ROUTE` | No | `LOCAL` | LLM backend to use. `LOCAL` = llama-cpp-python (GPU), `REMOTE` = OpenAI-compatible API |
| `API_KEY` | Only if `ROUTE=REMOTE` | — | Bearer token for the remote LLM API |
| `BASE_URL` | Only if `ROUTE=REMOTE` | — | Base URL for the remote LLM API (e.g. `https://api.fireworks.ai/inference/v1`) |
| `HF_ENDPOINT` | No | HuggingFace default | Mirror for model downloads. Set to `https://hf-mirror.com` if HuggingFace is blocked |
| `COQUI_TOS_AGREED` | No | `1` (set by script) | Must be `1` to enable Coqui TTS model downloads |

**Example `.env` for local inference:**
```env
ROUTE=LOCAL
HF_ENDPOINT=https://hf-mirror.com
COQUI_TOS_AGREED=1
```

**Example `.env` for remote inference:**
```env
ROUTE=REMOTE
API_KEY=fw_your_api_key_here
BASE_URL=https://api.fireworks.ai/inference/v1
COQUI_TOS_AGREED=1
```

---

## Dependency List

### System Dependencies (installed by `start.bash`)

| Package | Purpose |
|---------|---------|
| `build-essential`, `cmake` | C/C++ compilation (for llama-cpp-python) |
| `libgomp1`, `libstdc++6` | OpenMP and C++ runtime |
| `libcairo2-dev`, `libpango1.0-dev` | Vector graphics & text rendering (Manim) |
| `libgdk-pixbuf-2.0-dev`, `libffi-dev` | Image support and FFI |
| `shared-mime-info` | MIME type detection |
| `ffmpeg` | Audio/video encoding and assembly |
| `texlive`, `texlive-latex-extra`, `texlive-fonts-extra`, `texlive-latex-recommended` | LaTeX rendering (Manim math equations) |

### Python Dependencies (`requirements.txt`)

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | latest | REST + WebSocket API backend |
| `uvicorn` | (via fastapi) | ASGI server |
| `pydantic` | latest | Request/response data validation |
| `python-dotenv` | latest | `.env` file loading |
| `requests` | latest | HTTP client (remote LLM, web search) |
| `numpy` | latest | Numerical operations |
| `pytest` | latest | Test runner |
| `huggingface-hub` | 0.34.1 | Model download from HuggingFace |
| `manim` | 0.20.1 | Mathematical animation engine |
| `coqui-tts` | latest | Local text-to-speech synthesis |
| `moviepy` | latest | Video/audio manipulation |
| `langchain` | 1.3.14 | LLM chaining & prompt management |
| `langchain-core` | latest | LangChain core abstractions |
| `langchain-community` | 0.4.2 | LangChain community integrations |
| `langchain-huggingface` | ≥0.0.3 | HuggingFace LangChain integration |
| `ddgs` | 9.14.4 | DuckDuckGo search (web RAG) |
| `trafilatura` | 2.1 | Web content extraction |
| `sentence-transformers` | 2.7.0 | Sentence embeddings for RAG |
| `faiss-cpu` | latest | Vector similarity search |
| `rank_bm25` | latest | BM25 keyword search (hybrid RAG) |
| `pypdf` | 4.0.0 | PDF document loading |
| `gradio` | latest | Web UI frontend |
| `pillow` | latest | Image processing |

### Additional Python Dependencies (installed separately by `start.bash`)

| Package | Version | Purpose |
|---------|---------|---------|
| `torch` | 2.5.1+rocm6.2 | GPU tensor computation (AMD GPU via ROCm) |
| `torchaudio` | 2.5.1+rocm6.2 | Audio processing with GPU acceleration |
| `llama-cpp-python` | 0.3.33 | GGUF model inference with HIP/ROCm GPU offload |

---

## API Endpoints

The backend exposes a REST API on port `8000`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/jobs` | Create a new video generation job |
| `GET` | `/api/jobs/{job_id}` | Get job status and metadata |
| `DELETE` | `/api/jobs/{job_id}` | Cancel a running job |
| `WS` | `/api/ws/jobs/{job_id}` | Real-time progress stream (WebSocket) |
| `GET` | `/api/videos/{job_id}` | Download the completed MP4 video |
| `GET` | `/api/videos` | List all completed videos |
| `GET` | `/health` | Health check |

### Job creation payload

```json
{
  "user_query": "Explain how transformers work",
  "voice": "en",
  "video_quality": "720p",
  "conversation_id": null
}
```

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | AMD GPU with ROCm 6.2 support | AMD RX 7900 XTX or better |
| **VRAM** | 24 GB (Q8_0 Qwen 32B) | 32 GB+ |
| **RAM** | 32 GB | 64 GB |
| **Disk** | 50 GB free (model ~34 GB + outputs) | 100 GB+ |
| **OS** | Linux (Debian/Ubuntu recommended) | — |

> The LLM is configured to offload all layers to GPU (`n_gpu_layers=-1`). For CPU-only inference, edit `LLM/llm_local.py` and remove or set `n_gpu_layers=0`.

---

## Project Data & Outputs

| Path | Contents |
|------|----------|
| `./LLM/Models/` | Downloaded GGUF model files |
| `./output/` | Generated MP4 videos and intermediate audio/video clips |
| `./output/audio/` | Per-scene TTS audio files |
| `./data/edumanim.db` | SQLite database storing job history |
