# NexusAI Persistence Architecture

**Version:** 1.0

## Strategy

NexusAI uses a repository boundary between API routes and storage.

For zero-friction local development, the default database is SQLite.

For deployed and production-like environments, the same SQLAlchemy repository targets PostgreSQL by changing `DATABASE_URL`.

## Why This Split

- Local development requires no paid service or database installation.
- The API contract does not depend on a specific database vendor.
- PostgreSQL remains the intended durable deployment database.
- Alembic manages schema migrations.

## Current Persistent Entity

`worlds`

Future migrations will add:

- sources
- entities
- relationships
- events
- observations
- processing_jobs

## Production

Set:

`DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/nexusai`

Then run Alembic migrations before serving traffic.

## Important

SQLite is a development convenience, not the final Vercel persistence strategy. Vercel serverless filesystems must not be treated as durable database storage.
