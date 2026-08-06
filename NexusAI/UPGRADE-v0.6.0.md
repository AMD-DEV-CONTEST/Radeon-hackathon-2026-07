# NexusAI Extraction v0.6.0

## Save Path

Extract directly into the existing `NexusAI/` repository root and merge/replace files.

## Important

Update `apps/api/tests/test_health.py` to expect `0.6.0` if it still expects `0.5.0`.

## Run

```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Test

```cmd
python -m pytest -q
```

## Manual End-to-End Test

You can reuse your existing World and Source:

World:
`5b52e514-a87a-4225-888d-89d02678732d`

Source:
`4d403715-d963-4109-8232-e3d49b895def`

Call:

POST `/api/worlds/{world_id}/sources/{source_id}/extract`

Then call:

GET `/api/worlds/{world_id}/graph`

You should now see automatically extracted nodes and edges.

## Commit

```bash
git add .
git commit -m "feat(extraction): materialize document knowledge into graph"
git push
```
