# NexusAI Knowledge Graph v0.4.0

## Save path
Extract directly into the existing `NexusAI/` repository root and merge/replace files.

## Run
```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

The local SQLite startup automatically creates the new graph tables.

## Test
```cmd
python -m pytest -q
```

## Manual demo
Open `http://127.0.0.1:8000/docs`.

1. POST `/api/worlds`
2. POST two `/api/worlds/{world_id}/entities`
3. POST `/api/worlds/{world_id}/relationships`
4. GET `/api/worlds/{world_id}/graph`

This release also replaces deprecated FastAPI `on_event` startup handling with lifespan.

## Commit
```bash
git add .
git commit -m "feat(graph): implement persistent knowledge graph engine"
git push
```
