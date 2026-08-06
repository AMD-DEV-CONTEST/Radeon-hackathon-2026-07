# Decompile

**Turn any YouTube video into a production-ready software package.**

Decompile is a local-first AI software engineering studio built for the AMD Radeon AI Hackathon. Paste a video URL and the orchestration pipeline creates a PRD, architecture diagrams, QA plan, application scaffolds, deployment guidance, and a downloadable repository.

## Run it

```bash
npm install
npm run dev

# another terminal
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000
```

Or start both services with `docker compose up --build`.

## Local AI

The app uses no hosted AI APIs. It is runnable in deterministic local demo mode; see [Local AI runtime](docs/LOCAL_AI.md) to activate ROCm/HIP inference, Qwen vision, BGE embeddings, FAISS, yt-dlp, and PaddleOCR.

## API

- `POST /api/projects` starts a decompile run.
- `GET /api/projects/{id}` returns live orchestration state.
- `GET /api/projects/{id}/download` downloads the generated ZIP.
- `GET /api/memory/search?q=` searches locally retained project memory.
