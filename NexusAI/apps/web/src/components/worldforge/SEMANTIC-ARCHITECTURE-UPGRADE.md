# WorldForge Semantic Architecture Upgrade

Replace:
apps/web/src/components/worldforge/

with this folder.

This pass:
- converts people to human-scale NPC forms
- converts organizations into office/HQ architecture
- converts projects into workshop/research facilities
- converts systems into technology facilities
- converts places into restrained district landmarks
- converts unknown entities into neutral information pavilions
- reduces neon/glow and improves material realism
- removes the duplicate legacy ground/grid from KnowledgeCity
- keeps the current API-driven layout, selection, World View and Explorer Mode

Verification:
1. Keep FastAPI on port 8000.
2. From apps/web run: npm run build
3. Then run: npm run dev
