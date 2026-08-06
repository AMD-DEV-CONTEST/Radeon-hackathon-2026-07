# NexusAI Persistence v0.3.0

## Save Path

Extract this ZIP directly into your existing `NexusAI/` repository root.

Allow folder merging and replacement.

## What Changes

- Adds SQLAlchemy persistence.
- Adds Alembic migrations.
- Uses SQLite by default for zero-setup local development.
- Supports PostgreSQL via `DATABASE_URL`.
- Makes Worlds survive API restarts.
- Adds `pytest.ini`, so pytest no longer needs manual `PYTHONPATH` setup.

## Install

From `NexusAI/`:

```cmd
pip install -r apps/api/requirements.txt
```

## Run

```cmd
set PYTHONPATH=%CD%;%CD%\apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Test

Now simply run:

```cmd
python -m pytest -q
```

## Persistence Test

1. Open `http://127.0.0.1:8000/docs`
2. POST a new World.
3. Stop FastAPI.
4. Start FastAPI again.
5. GET `/api/worlds`.

The World should still exist.

## PostgreSQL Migration

When a PostgreSQL database is available:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/nexusai
```

Run from `apps/api` with repository root included in `PYTHONPATH`:

```cmd
alembic upgrade head
```

## Commit

```bash
git add .
git commit -m "feat(persistence): add SQLAlchemy storage and database migrations"
git push
```
