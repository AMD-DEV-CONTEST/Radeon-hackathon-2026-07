# NexusAI Semantic Retrieval v0.7.0

## Save Path

Extract directly into the existing `NexusAI/` repository root and merge/replace files.

## Install

```cmd
pip install -r apps/api/requirements.txt
```

## Health Test

Update `apps/api/tests/test_health.py` to expect `0.7.0`.

## Run

```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Test

```cmd
python -m pytest -q
```

## Manual Test

Reuse your existing World:

`5b52e514-a87a-4225-888d-89d02678732d`

Call:

GET `/api/worlds/{world_id}/search`

Try query:

`NexusAI backend`

Or:

`research laboratory Bengaluru`

The current local baseline ranks chunks using word and bigram vector similarity.

## Important Architecture Note

v0.7.0 establishes the semantic retrieval interface with a zero-cost CPU baseline. v0.8.0 replaces or supplements this with real dense embeddings on AMD Radeon Cloud and measures the improvement.

## Commit

```bash
git add .
git commit -m "feat(retrieval): add local semantic search baseline"
git push
```
