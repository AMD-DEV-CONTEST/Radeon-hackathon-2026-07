# Installation Guide

## Prerequisites
- Python **3.13.x**
- Node.js **LTS**
- Ollama installed locally

## 1) Install backend dependencies
```bash
pip install -r requirements.txt
```

## 2) Start Ollama
```bash
ollama serve
```

## 3) Pull at least one preferred model
Priority order used by AgentFlow AI:
```bash
ollama pull qwen2.5:7b
ollama pull llama3.2:3b
ollama pull mistral:7b
```

You do **not** need all three. The app automatically detects what's installed and falls back safely.

## 4) Start the FastAPI backend
```bash
python -m uvicorn app.main:app --reload
```

Backend URLs:
- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`

## 5) Install frontend dependencies
```bash
npm install
```

## 6) Start the React frontend
```bash
npm run dev
```

Frontend URL:
- `http://127.0.0.1:5173`

## Notes
- If Ollama is not running, the UI shows a helpful warning instead of crashing.
- Sample files are available in `sample_data/`.
- Runtime state is stored in `runtime_data/`.
