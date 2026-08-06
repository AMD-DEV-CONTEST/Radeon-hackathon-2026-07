# WorldForge Biome Asset System

Generation 5 introduces a deterministic biome-aware asset layer.

## Pipeline

EnvironmentRenderSpec -> BiomeAssetRegistry -> BiomeScatter -> BiomeAsset

`BiomeAsset` uses a primitive fallback when no GLB URL is registered. This keeps every biome renderable while production assets are added incrementally.

## Production GLB upgrade

Add optimized assets under:

public/worldforge/assets/biomes/<biome>/

Then add a `url` to the matching definition in `BiomeAssetRegistry.ts`.

Recommended production asset constraints:
- glTF/GLB
- compressed textures
- PBR materials
- sensible polygon budgets
- shared texture atlases where possible
- LOD variants for dense vegetation

The scatter system is deterministic, so re-renders do not randomly move environmental assets.
