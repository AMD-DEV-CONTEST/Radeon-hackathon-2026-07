# MoonRabbits — AMD AI DevMaster Hackathon 2026-07 · Track 2

A storytelling AI ceramic band: a multi-agent narrative product built around
Chinese ceramic glaze colors. Four expert agents work in parallel, coordinated
by a Foreman module with cloud tool calling — a local LLM as the always-available
baseline, enhanced by the Radeon Cloud model API.

## Hardware & System Environment

| Item | Specification |
|---|---|
| GPU | AMD Radeon Pro W7900 (gfx1100, 48 GB VRAM) |
| ROCm | 7.2.1 |
| OS / Python | Ubuntu · Python 3.12.3 |
| Inference runtimes | Ollama (local baseline, port 11434) + optional vLLM ROCm build (port 8001) |
| Local model | qwen2.5:14b-instruct-q8_0 (measured 42.6 tok/s single-stream) |
| Quantized model | Qwen2.5-14B-Instruct AWQ (served by vLLM — official quantization bonus) |

## Architecture

- **Four expert agents** (Chinese mode): Historian / Scientist / Muse / Narrator
  - Knowledge base: ChromaDB with dual-path retrieval — keyword + vector (`moonrabbits_agents.py`)
- **Foreman** (`foreman.py`): prefers the Radeon Cloud model API (tool calling,
  built-in tools such as dynasty era lookup), automatically degrades to the local
  Ollama chain when the cloud is unreachable; the key file `radeon_api_key.txt`
  is **never committed to git**
- **Frontend**: single-file `index.html`, rendering agent answers with tool
  badges (`foreman.badges`) and a backend indicator
- **Session persistence**: `sessions_store.json` — conversation history survives
  service restarts (evidence for the official "local multi-turn memory" feature)

## Quick Start

```bash
# 1. Dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Local inference baseline (Ollama)
ollama serve &
ollama pull qwen2.5:14b-instruct-q8_0

# 3. Build the knowledge base (generates chroma/ and kb_text_index.json)
python ingest_kb.py

# 4. Start the product (http://localhost:8000)
python app.py

# 5. Optional: Foreman cloud backend (auto-degrades to local when key absent)
echo "<your-radeon-cloud-key>" > radeon_api_key.txt

# 6. Optional: vLLM quantized inference service (port 8001, AWQ)
# See benchmarks and the separate vLLM venv notes
```

## File Overview

| File | Role |
|---|---|
| `app.py` | Main product service (port 8000): sessions, 4-agent orchestration, safety gate, SSE streaming |
| `moonrabbits_agents.py` | Retrieval (ChromaDB dual-path) + Ollama chain wrappers |
| `foreman.py` | Foreman module: Radeon Cloud API + built-in tools + degradation chain |
| `ingest_kb.py` | Knowledge-base ingestion (kb_entries.jsonl → chroma) |
| `index.html` | Frontend page |
| `kb_entries.jsonl` / `kb_entries_core.jsonl` | Ceramic knowledge-base entries |
| `tools/` | Documentary episode batch-generation pipeline (serial over Ollama, with self-checking quality gates) |

## Content Production Pipeline

The batch scripts under `tools/` drive the same local inference chain to produce
documentary "episode packages" (episode title / 60s narration / 3-shot storyboard /
bilingual text-to-image prompts / subtitles). Built-in topic-list self-cleaning
and a triple quality gate (five-section structure + citation markers + word count).
Outputs land in `episodes/` (not committed to git).

## Security Notes

- `radeon_api_key.txt` is listed in `.gitignore` and must never be committed
- All external input passes through a safety gate (word-boundary regex filtering)
