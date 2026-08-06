# WorldForge District Generation Upgrade

This generation adds:
- contextual district architecture that does not create fake knowledge entities
- deterministic vegetation and street furniture
- subdued district plazas instead of graph-like glowing circles
- less intrusive relationship presentation
- layout bounds helper for adaptive camera framing
- semantic collider generation utility for architecture-aware Explorer collision

The contextual buildings are scenery only. Semantic entities remain sourced exclusively from the knowledge graph.

Install by replacing:
apps/web/src/components/worldforge/

Verification:
npm run build
npm run dev

Suggested commit:
git add apps/web/src/components/worldforge
git commit -m "feat(worldforge): generate contextual districts and semantic world infrastructure"
