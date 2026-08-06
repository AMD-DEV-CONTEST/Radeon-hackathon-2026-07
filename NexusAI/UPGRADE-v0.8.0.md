# NexusAI Radeon GPU v0.8.0
## Save path
Extract into the existing `NexusAI/` repository root and merge/replace files.

## Required manual merge
In `apps/api/app/main.py`:
1. Change FastAPI version to `0.8.0`.
2. Import:
```python
from app.routes.compute import router as compute_router
from app.routes.dense_search import router as dense_search_router
```
3. Add:
```python
app.include_router(dense_search_router, prefix="/api")
app.include_router(compute_router, prefix="/api")
```

In `apps/api/app/routes/health.py`, return version `0.8.0`.
In `apps/api/tests/test_health.py`, expect `0.8.0`.

## Local test
```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
set NEXUS_EMBEDDING_PROVIDER=auto
python -m pytest -q
python scripts\check_radeon_environment.py
```
CPU FALLBACK on Windows is correct.

## Commit before launching Radeon Cloud
```bash
git add .
git commit -m "feat(radeon): add ROCm embedding provider and GPU benchmark framework"
git push
```

Only then launch the GPU and follow `RADEON-CLOUD-RUNBOOK.md`.
