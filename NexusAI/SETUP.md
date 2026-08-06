# NexusAI Foundation v0.1.0 Setup

## Save Path

Extract this bundle into the **root of your existing NexusAI repository**.

The extracted folders such as `apps`, `nexus`, `worlds`, and `ai` should sit beside your existing `docs` folder.

## Run the API

```bash
cd apps/api
python -m venv .venv
```

Activate the environment, then:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify:

`http://localhost:8000/api/health`

Expected JSON:

```json
{
  "status": "healthy",
  "service": "nexus-api",
  "version": "0.1.0"
}
```

## Run the Web App

Open another terminal:

```bash
cd apps/web
npm install
```

Copy `.env.example` to `.env.local`, then:

```bash
npm run dev
```

Open:

`http://localhost:3000`

The status badge should change to `NEXUS CORE ONLINE`.

## Vercel

Create a Vercel project with:

- Root Directory: `apps/web`
- Framework Preset: Next.js
- Environment variable:
  - `NEXT_PUBLIC_API_URL=<your deployed API URL>`

For local development this remains:

`http://localhost:8000`

## Recommended Commit

```bash
git add .
git commit -m "feat(core): initialize NexusAI platform foundation"
git push
```
