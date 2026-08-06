# WorldForge Terrain Fidelity

Generation 7 replaces the visually flat biome plane with deterministic biome-specific elevation.

## Features
- deterministic value-noise/fBM terrain
- biome-specific elevation profiles
- dunes for desert worlds
- amplified ridges for mountain worlds
- snow-bank variation for arctic worlds
- coastal elevation bias
- deliberately flatter urban terrain
- flattened settlement center
- reduced elevation along principal cross-roads
- terrain-aware environmental asset placement

## Gameplay constraint

The generated terrain intentionally suppresses elevation around the central settlement and main cross-road corridors. This is a visual-fidelity foundation, not a full physics terrain controller. Player/camera ground-following and slope-aware collision should be implemented before aggressive elevation is introduced inside navigable city districts.

## Next visual layer

Production PBR terrain materials should consume albedo, normal, roughness, AO and displacement textures while retaining this geometry system.
