# Validation Report

Validation date: 2026-08-04

## Environment used
- Python: `3.13.14`
- Node.js: `v20.20.2`
- npm: `10.8.2`

## Python dependency verification

Top-level requirements were validated before generation:

| Package | Version | PyPI exists | Requires Python | Windows wheel available | Notes |
|---|---:|---|---|---|---|
| fastapi | 0.141.1 | Yes | `>=3.10` | Yes (`py3-none-any`) | Used for backend API |
| uvicorn | 0.52.1 | Yes | `>=3.10` | Yes (`py3-none-any`) | Used to run the backend |
| python-multipart | 0.0.32 | Yes | `>=3.10` | Yes (`py3-none-any`) | Required for file uploads |
| pypdf | 6.14.2 | Yes | `>=3.9` | Yes (`py3-none-any`) | Used for PDF extraction |
| chromadb | 1.5.9 | Yes | `>=3.9` | Yes (`cp39-abi3-win_amd64`) | Used for offline vector retrieval |

## Python install validation
Command:
```bash
pip install -r requirements.txt
```

Result:
- Success on Python 3.13.14
- No manual dependency edits required
- No source compilation triggered during this validation run

## Backend runtime validation
Command:
```bash
python -m uvicorn app.main:app --reload
```

Result:
- Started successfully
- FastAPI app booted without import errors
- Health endpoint returned HTTP 200
- App handled missing Ollama gracefully with a helpful message

Sample response from `GET /api/system/health`:
```json
{
  "ok": true,
  "ollama_running": false,
  "selected_model": null,
  "available_models": [],
  "database_ready": true,
  "chroma_ready": true,
  "message": "Ollama is unavailable. Start it with 'ollama serve' and pull a model like 'ollama pull qwen2.5:7b'. Details: <urlopen error [Errno 111] Connection refused>"
}
```

## Backend tests
Command:
```bash
python -m unittest discover -s tests -v
```

Result:
- 3 tests passed
- Verified health endpoint, chat fallback path, and embedding generation

## npm dependency verification
Validated package versions:

| Package | Version | Registry exists | Node compatibility |
|---|---:|---|---|
| react | 19.2.8 | Yes | `>=0.10.0` |
| react-dom | 19.2.8 | Yes | compatible |
| vite | 8.2.0 | Yes | `^20.19.0 || >=22.12.0` |
| @vitejs/plugin-react | 6.0.5 | Yes | `^20.19.0 || >=22.12.0` |
| tailwindcss | 4.3.3 | Yes | compatible |
| @tailwindcss/vite | 4.3.3 | Yes | compatible |

## Frontend install validation
Command:
```bash
npm install
```

Result:
- Success
- 0 vulnerabilities reported by npm audit summary during validation

## Frontend runtime validation
Command:
```bash
npm run dev
```

Result:
- Started successfully on port 5173
- Preview host issue was fixed by enabling `server.allowedHosts: true`
- Frontend proxy to backend `/api` verified

## Production build validation
Command:
```bash
npm run build
```

Result:
- Success
- Vite production build completed without errors

## Final checklist
- [x] `requirements.txt` installs successfully
- [x] `package.json` installs successfully
- [x] `npm install` works
- [x] `pip install` works
- [x] `uvicorn` starts without errors
- [x] `npm run dev` starts successfully
- [x] No missing imports found during runtime validation
- [x] No API keys required
- [x] Offline Ollama-only architecture
- [x] Automatic model detection and fallback implemented
- [x] Helpful error path when Ollama is offline
- [x] Python 3.13 compatible in the validated environment
