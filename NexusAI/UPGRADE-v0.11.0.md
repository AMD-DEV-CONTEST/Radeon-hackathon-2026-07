# NexusAI WorldForge v0.11.0 - Relationship-Aware Knowledge City

Built on the validated v0.10.0 knowledge graph integration.

## What changes

WorldForge no longer places every knowledge entity on one generic radial ring.

### Place entities become districts
Examples:
- Kochi -> Kochi District
- Bengaluru -> Bengaluru District

### Spatial relationships influence placement
These relationship types cluster entities around place districts:
- LIVES_IN
- LOCATED_IN
- BASED_IN
- WORKS_AT
- WORKS_IN
- VISITED

### Knowledge hubs influence local clusters
Organizations, projects, systems, labs and companies become hubs.

Relationships such as:
- WORKS_WITH
- MAINTAINS
- ADVISES
- CREATED
- CONNECTED_TO
- CONTAINS
- LEADS

pull connected entities toward those hubs when they do not already belong to a place district.

### Disconnected knowledge
Entities with no usable spatial relationship are placed on a deterministic outer ring.

### Visual additions
- green district boundary rings
- district labels
- relationship links follow graph-driven positions
- existing entity colors, labels and connection prominence remain

## Install

Replace:

`apps/web/src/components/worldforge/WorldForgeScene.tsx`

No database migration is required.

Keep the existing `.env.local` WorldForge world ID.

Restart Next.js after replacement:

```bash
cd apps/web
npm run dev
```

## Validate

Using the NexusAI test document, World View should now visually separate knowledge
around place districts such as Kochi and Bengaluru when the corresponding
LIVES_IN / LOCATED_IN / VISITED relationships exist.

## Commit after validation

```bash
git add apps/web/src/components/worldforge/WorldForgeScene.tsx
git commit -m "feat(worldforge): generate relationship-aware knowledge districts"
git push
```

## Next milestone

v0.12 can evolve district markers into actual graph-generated architecture:
- organizations become named buildings
- projects become landmark structures
- people become NPCs
- roads are generated from semantic relationships
- interaction panels expose source evidence and relationship context
