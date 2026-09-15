# Find it

**Find it** helps you find things by recording and uploading videos, then
analysing them. It is a self-contained FastAPI web app that catalogues your
recordings, extracts frame descriptions and audio transcriptions with local AI
models, and lets you search across everything — or ask an agentic chat — to
locate the moment or object you are looking for.

- **Backend:** Python + FastAPI + SQLite (no external database required).
- **Media processing:** `ffmpeg` / `ffprobe` for probing, preview frames, and
  background MP4 transcoding.
- **AI services:** Ollama (VLM + agent LLM) and a local whisper.cpp server (ASR).
- **Frontend:** plain HTML/CSS/JS served from `static/`.
- **Tests:** pytest suite with mock mode for the agentic parts.

> This archive contains **source code, setup scripts, and example configuration
> only**. No large binaries, videos, databases, API keys, or credentials are
> included. Models and the whisper.cpp server are downloaded on demand by the
> provided scripts.

## Repository layout

```
.
├── main.py                 # FastAPI app
├── ai_clients.py           # VLM / ASR / agent-LLM client wrappers
├── agentic.py              # Agentic retrieval chat backend
├── static/                 # Frontend (index.html, view.html, search.html, chat.html, style.css)
├── scripts/                # Setup / serving helpers
│   ├── setup_ollama.sh     # Install Ollama and pull models
│   ├── start_ollama.sh     # Start the Ollama daemon
│   ├── setup_whisper.sh    # Download whisper.cpp Vulkan server + model
│   ├── serve_whisper.sh    # Start the local ASR server
│   └── import_output_log.py# Import existing transcription JSON into the DB
├── models/whisper/         # Whisper server + model (created by setup_whisper.sh)
├── reference/              # Design notes and external links
├── requirements.txt
├── requirements-dev.txt
├── setup.sh                # Create venv and install Python deps
├── launch.sh               # Start the web app
├── .env.example            # Example configuration (copy to .env)
└── README.md               # This file
```

Runtime data (`uploads/`, `videos.db`) is created automatically when the app
starts and is git-ignored.

## Prerequisites

- Ubuntu/Debian-like Linux (tested on Ubuntu 25.04).
- `ffmpeg` and `ffprobe`:
  ```bash
  sudo apt update
  sudo apt install -y ffmpeg
  ```
- Vulkan runtime libraries for the whisper.cpp Vulkan backend:
  ```bash
  sudo apt install -y libgomp1 libvulkan1 mesa-vulkan-drivers
  ```
- [astral `uv`](https://docs.astral.sh/uv/) for Python environment management:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- An internet connection to download models the first time.

## Quick start

### 1. Set up the Python environment

From this directory:

```bash
./setup.sh
```

This creates `./.venv`, installs the runtime dependencies, and creates the
`uploads/` directory.

### 2. Set up the AI backends

#### Ollama (VLM + agent LLM)

```bash
./scripts/setup_ollama.sh
```

This installs Ollama (if needed) and pulls:

- `minicpm-v4.5:8b` — vision-language model for describing frames.
- `gpt-oss:20b` — text model used by the agentic retrieval chat.

Start Ollama in a separate terminal:

```bash
./scripts/start_ollama.sh
```

#### Whisper.cpp ASR server

```bash
./scripts/setup_whisper.sh
```

This downloads the prebuilt Vulkan server and the
`ggml-large-v3-turbo-q5_0` model into `models/whisper/`.

Start the ASR server in a separate terminal:

```bash
./scripts/serve_whisper.sh
```

### 3. Configure the app

Copy the example environment file and review the settings:

```bash
cp .env.example .env
```

The defaults in `.env.example` already point to the local Ollama and whisper
servers started above. If you run the AI services on different hosts/ports,
edit `.env` accordingly.

### 4. Launch the web app

```bash
./launch.sh
```

Open http://localhost:8090 in your browser. API docs are at
http://localhost:8090/docs.

## Running without real AI services (mock mode)

To try the app or run tests without Ollama/whisper, set `MOCK_MODE=true`:

```bash
MOCK_MODE=true ./launch.sh
```

In mock mode the VLM/ASR/agent clients return deterministic placeholders.
The upload, search, and chat endpoints still work end-to-end.

## Running tests

Install dev dependencies:

```bash
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

Run the full suite:

```bash
pytest -q
```

Some tests need a real video sample. Set `SAMPLE_TS` to skip them if you do not
have one:

```bash
SAMPLE_TS=/path/to/sample.ts pytest -q
```

Run only the mock/unit tests:

```bash
pytest -q -m "not needs_sample" test_agentic.py test_demo.py
```

## Configuration reference

Key environment variables (see `.env.example` for the full list):

| Variable | Purpose | Default |
|----------|---------|---------|
| `VLM_API_URL` | OpenAI-compatible endpoint for the vision model | `http://localhost:11434/v1/chat/completions` |
| `VLM_MODEL_NAME` | Vision model name | `minicpm-v4.5:8b` |
| `ASR_API_URL` | whisper.cpp server endpoint | `http://127.0.0.1:8080/inference` |
| `AGENT_LLM_API_URL` | OpenAI-compatible endpoint for the agent | `http://localhost:11434/v1/chat/completions` |
| `AGENT_LLM_MODEL` | Agent LLM name | `gpt-oss:20b` |
| `MOCK_MODE` | Use mock AI clients | `false` |
| `HOST` / `PORT` | Bind address for the web app | `0.0.0.0` / `8090` |

## Notes

- The app stores uploaded videos in `uploads/` and metadata in `videos.db`
  inside the project root. Both are created automatically and are safe to
  delete; the DB schema is recreated on startup.
- Background workers handle MP4 transcoding and chunked transcription. They run
  inside the same process as the web server.
- The whisper.cpp server is linked against Vulkan and should run on most modern
  AMD/Intel/NVIDIA GPUs with Vulkan drivers. If Vulkan is unavailable it may
  fall back to CPU, but performance will be much lower.
- For ROCm-specific build instructions (if you prefer to compile whisper.cpp
  yourself), see `reference/build_whisper_cpp_rocm.txt`.

## Links

- Ollama: https://ollama.com
- whisper.cpp release used by this project: https://github.com/lemonade-sdk/whisper.cpp-rocm
- whisper.cpp models: https://huggingface.co/ggerganov/whisper.cpp
- uv: https://docs.astral.sh/uv/

## License

Hackathon project — provided as-is for reference and further development.
