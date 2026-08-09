# Troubleshooting

## PowerShell blocks scripts

Use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-all.ps1 -DemoMode
```

## `npm.ps1` cannot be loaded

Use `npm.cmd`, as the project scripts do.

## Python is not found

Install Python 3.11 or 3.12 and enable **Add Python to PATH**. Reopen the terminal.

## PostgreSQL connection fails

Use `-DemoMode` first. For PostgreSQL, verify the service is running and check `DB_URL`, `DB_USER`, and `DB_PASSWORD`.

## AI service is down

Run:

```powershell
cd ai-service
.\.venv\Scripts\python.exe run.py
```

Check `http://127.0.0.1:8000/ai/health`.

## Scanned PDF has no text

Install Tesseract OCR and Poppler, then configure `TESSERACT_CMD`. The main demo uses text documents and does not depend on OCR.

## Gemini fails

Remove or correct `GEMINI_API_KEY`. The system will continue in offline evidence mode.

## Ports are already in use

Stop existing Java, Node, or Python development servers, or update the configured ports.

## Reset demo data

Stop all services, delete `data/indusmind-demo.mv.db`, and clear the contents of `data/chroma`, `data/index`, and `data/uploads` while preserving `.gitkeep` files.

