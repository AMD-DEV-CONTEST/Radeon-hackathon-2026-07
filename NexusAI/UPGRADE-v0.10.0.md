# NexusAI v0.10.0 - Knowledge-Driven WorldForge

This patch was built against the uploaded current NexusAI project.

## What it adds

### Backend
New endpoint:

`GET /api/worlds/{world_id}/worldforge`

Returns:
- entities
- entity type
- description/properties
- connection count
- relationships

### Frontend
WorldForge now loads a configured NexusAI world and renders:
- people as glowing person markers
- places as green district/anchor markers
- organizations as purple structures
- projects/systems as magenta landmarks
- unknown entity types as blue knowledge structures
- relationships as glowing spatial links
- labels with entity names and connection counts

The existing procedural city, WASD, jump, sprint, collisions, World View,
player beacon, and camera controls are preserved.

## Install

Copy the patch contents into the NexusAI repository, preserving paths.

### Configure the world

In `apps/web/.env.local`, add:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WORLDFORGE_WORLD_ID=YOUR_WORLD_UUID
```

For the test world used earlier, the UUID was:

`5b52e514-a87a-4225-888d-89d02678732d`

Use that only if it still exists in your current local database.

## Ensure extraction has run

The source upload alone creates chunks. The knowledge graph must also contain
entities/relationships. For a source that has not been extracted, call:

`POST /api/worlds/{world_id}/sources/{source_id}/extract`

Then verify:

`GET /api/worlds/{world_id}/worldforge`

## Test backend

From the repository root:

```bash
python -m pytest -q
```

## Run

API:

```bash
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

Web:

```bash
cd apps/web
npm run dev
```

Open `/worldforge`.

The bottom-right HUD should report knowledge entity/link counts.

## Commit

```bash
git add .
git commit -m "feat(worldforge): generate 3D world from knowledge graph"
git push
```

## Scope note

v0.10.0 is the first knowledge-to-world bridge. It deliberately uses deterministic
radial placement for knowledge entities so the integration is testable.

Later milestones can evolve this into:
- place-based districts
- organizations as full buildings
- people as animated NPCs
- relationship-aware clustering
- click/interact panels
- graph-driven roads
- semantic district generation
