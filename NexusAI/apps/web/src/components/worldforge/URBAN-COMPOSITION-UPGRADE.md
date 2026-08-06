# WorldForge Urban Composition Upgrade

Generation goals:
- adaptive terrain footprint based on inhabited graph bounds
- central Nexus Plaza
- district-aware arterial road network
- smaller, more natural vegetation
- more varied contextual architecture
- less unused world-grid space
- camera framing utility for graph-aware World View
- preserve semantic entities, districts, Explorer Mode and API-driven knowledge

No contextual object is promoted into the knowledge graph.

Install:
Replace apps/web/src/components/worldforge/ with this folder.

Test:
cd apps/web
npm run build
npm run dev

Commit:
git add apps/web/src/components/worldforge
git commit -m "feat(worldforge): introduce adaptive urban composition and district-aware world layout"
