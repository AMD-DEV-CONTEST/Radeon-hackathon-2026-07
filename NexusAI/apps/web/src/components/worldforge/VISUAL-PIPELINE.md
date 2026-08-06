# Generation 5 — Visual Pipeline

## Proximity UI
Entity labels now fade with camera distance. Minor entities disappear earlier; place and organization landmarks remain readable farther away. Relationship labels remain local to selected connections.

## Production asset architecture
`AssetRegistry.ts` maps semantic kinds to GLB/GLTF assets.
`SemanticAsset.tsx` loads registered assets and preserves the existing procedural renderer as a fallback.

Recommended public asset layout:

public/worldforge/assets/
  characters/
  buildings/
  landmarks/
  vegetation/
  props/
  materials/

Use glTF 2.0 / GLB assets with PBR materials (base color, normal, roughness/metalness, AO where useful). Keep texture sizes and polygon counts appropriate for a browser renderer.

This pipeline does not include copyrighted RDR2 assets. It provides the infrastructure for higher-fidelity original/licensed assets.

Commit:
git add apps/web/src/components/worldforge
git commit -m "feat(worldforge): add proximity UI and production-ready visual asset pipeline"
