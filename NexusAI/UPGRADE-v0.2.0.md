# NexusAI Core v0.2.0

## Save Path
Extract this ZIP directly into the root of your existing `NexusAI/` repository and allow folder merging/replacement.

## Run API on Windows PowerShell
From the `NexusAI/` repository root:

```powershell
$env:PYTHONPATH = "."
.\apps\api\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
uvicorn app.main:app --app-dir apps/api --reload --port 8000
```

## Test
```powershell
$env:PYTHONPATH = "."
pytest apps/api/tests -q
```

## Verify
- `http://localhost:8000/api/health`
- `http://localhost:8000/api/world-catalog`
- `http://localhost:8000/api/worlds`
- `http://localhost:8000/docs`

Persistence is intentionally in-memory in v0.2.0. PostgreSQL comes next, after validating the canonical World Model and API contract.

## Commit
```bash
git add .
git commit -m "feat(core): implement universal world model and world API"
git push
```
