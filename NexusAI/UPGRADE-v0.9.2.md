# NexusAI WorldForge v0.9.2

## Purpose
Adds the procedural city foundation while preserving the agreed dual-mode roadmap:
- World View: current orbit/bird's-eye exploration.
- Explorer Mode: future WASD + mouse-look street-level navigation.

The street grid and building spacing are intentionally designed for the player controller planned for v0.9.3.

## Save path
Replace:

`NexusAI/apps/web/src/components/worldforge/WorldForgeScene.tsx`

with the included file.

## Run
From `NexusAI/apps/web`:

```bash
npm run dev
```

Open:

`http://localhost:3000/worldforge`

## Expected
- larger procedural city
- walkable road grid
- varied building heights
- glowing building windows
- street lights
- two district foundations
- landmark towers
- upgraded animated Nexus Core
- cinematic fog and lighting
- existing orbit-based World View

## Important
This milestone does NOT add WASD yet. It builds the city layout specifically for v0.9.3 Explorer Mode.

## Commit
```bash
git add .
git commit -m "feat(worldforge): add procedural explorer-ready city"
git push
```
