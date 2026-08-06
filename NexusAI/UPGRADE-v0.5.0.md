# NexusAI Universal Ingestion v0.5.0

## Save Path

Extract directly into the root of your existing `NexusAI/` repository and merge/replace files.

## Install

```cmd
pip install -r apps/api/requirements.txt
```

## Run

```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Test

Update the old health test expectation from `0.4.0` to `0.5.0` if necessary, then:

```cmd
python -m pytest -q
```

## Manual Test

Open `http://127.0.0.1:8000/docs`.

1. Create a World.
2. Use POST `/api/worlds/{world_id}/sources/upload`.
3. Upload TXT, JSON, PDF, or DOCX.
4. Copy the returned source ID.
5. Call GET `/api/worlds/{world_id}/sources/{source_id}/chunks`.

## Commit

```bash
git add .
git commit -m "feat(ingestion): implement universal document ingestion pipeline"
git push
```
