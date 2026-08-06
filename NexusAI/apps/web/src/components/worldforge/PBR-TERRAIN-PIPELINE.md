# PBR Terrain Pipeline

Generation 8 adds a production-ready terrain material resolver without making texture files mandatory.

## Runtime

Biome -> TerrainMaterialProfile -> texture loader -> MeshStandardMaterial

Supported maps:
- albedo/base color
- normal
- roughness
- ambient occlusion

Missing maps fail softly. The terrain keeps its biome-specific fallback color and scalar material properties.

## Asset path

`public/worldforge/assets/terrain/<biome>/`

Expected filenames:
`albedo.jpg`, `normal.jpg`, `roughness.jpg`, `ao.jpg`.

## Why textures are not bundled

The renderer and asset contract belong in source control. Production texture packs should be selected based on licensing, resolution, compression, visual direction, and download budget rather than silently shipping arbitrary generated image files.
