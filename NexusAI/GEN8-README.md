# NexusAI PBR Terrain Materials — Generation 8

Built against the uploaded post-Generation-7 WorldForge source.

Copy `apps/` into the NexusAI repository root.

New source:
- terrainMaterialProfiles.ts
- useTerrainTextures.ts
- PBRTerrainMaterial.tsx
- PBR-TERRAIN-PIPELINE.md

Replace:
- BiomeTerrain.tsx

Also adds the expected public terrain asset directory structure with README placeholders.

Run:
cd apps/web
npm run build
