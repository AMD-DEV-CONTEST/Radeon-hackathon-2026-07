<div align="center">
  <img src="assets/earth_pixelated.svg" alt="Aetheris Logo" width="96" height="96" />
  <h1>Aetheris</h1>
  <p><b>A local, private AI coding agent, desktop app (Flutter) + terminal, running entirely on your own AMD Radeon GPU</b></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-informational" alt="Platform" />
    <img src="https://img.shields.io/badge/GPU-AMD%20Radeon-ED1C24" alt="GPU" />
  </p>
</div>

---

This folder is the agent itself: `core/` is the backend (FastAPI, tool dispatch, memory, skills) and the integration with **VTE**, the inference engine this project also built from scratch; `aetheris_ui/` is the Flutter desktop client.

For what Aetheris actually does, the full capability list, and the Track 2 submission writeup, see the repository root: [`../README.md`](../README.md) and [`../PROJECT_SPECIFICATION.md`](../PROJECT_SPECIFICATION.md).

## Running this folder specifically

Full instructions (Windows app, Windows terminal, Linux terminal) live in the root README's [Quickstart](../README.md#quickstart); short version, from inside this folder:

```bash
python -m venv .venv
.venv\Scripts\pip install --upgrade pip          # Windows
.venv/bin/pip install --upgrade pip              # Linux
.venv\Scripts\pip install -e "..\VTE"            # Windows
.venv/bin/pip install -e "../VTE"                # Linux
.venv\Scripts\pip install -r requirements.txt    # Windows
.venv/bin/pip install -r requirements.txt        # Linux
.venv\Scripts\vte pull llama3.1:8b-instruct-q4_k_m       # Windows
.venv/bin/vte pull llama3.1:8b-instruct-q4_k_m            # Linux
```

Llama 3.1 8B Instruct is the default: noticeably better at the tool-calling this agent depends on (deciding when to read/write a file, run a command, or update a plan) than a tiny demo model, and it correctly mirrors the user's input language every time. Downloads from Hugging Face ([Meta-Llama-3.1-8B-Instruct-GGUF](https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF)) into `VTE/Model/`, needs about 5 GB VRAM. If your GPU is tighter on VRAM, `qwen2.5:1.5b-q4_k_m` (~1 GB) is the lighter fallback, selectable from the same Flutter UI model dropdown. (IBM Granite 4.1 30B was tried first and is a strong reasoner, but reproducibly defaults to Portuguese/Spanish greetings under this agent's real tool-documentation system prompt; see [Known limitations](../VTE/docs/LIMITATIONS.md#model-compatibility).)

Then either build the Flutter UI (`cd aetheris_ui && flutter run -d windows`, Windows only for now) or run the backend directly and talk to it from a terminal:

```bash
.venv\Scripts\python app.py       # Windows, in one terminal
.venv/bin/python app.py           # Linux, in one terminal

.venv\Scripts\python scripts\chat.py   # Windows, in a second terminal
.venv/bin/python scripts/chat.py       # Linux, in a second terminal
```

First run generates a local login and writes it to `GENERATED_LOGIN_READ_AND_DELETE.txt` (only relevant to the Flutter UI, the terminal client doesn't need it, see [Architecture](../PROJECT_SPECIFICATION.md#2-agent-architecture)). Open it, note the credentials, delete the file.

## Layout

- **`core/`**: FastAPI backend (`app.py`), tool implementations (`core/utils/tools.py`), the agent's round loop (`core/utils/agent.py`), auth, memory, skills.
- **`aetheris_ui/`**: Flutter desktop client.
- **`scripts/chat.py`**: terminal chat client, same backend and agent loop the Flutter UI uses, works on both Windows and Linux.
