# Production Environment Asset Pipeline

Generation 9 adds the contract for replacing procedural trees and rocks with real GLB assets.

Production assets are intentionally opt-in:
`NEXT_PUBLIC_WORLDFORGE_PRODUCTION_ASSETS=true`

Do not enable it until the GLB paths in `environmentAssetManifest.ts` exist.

## Recommended free sources
- Poly Haven: CC0 realistic models, particularly trees, rocks, plants.
- Quaternius: CC0 game-ready packs, useful when performance matters more than photorealism.

For the RDR2-like direction, prefer realistic Poly Haven source models, then optimize them for the web: reduce texture resolution, generate LODs, compress meshes/textures, and keep source attribution metadata even when CC0 does not require attribution.

Never hotlink third-party model files. Download, optimize, and serve assets locally from `public/worldforge/assets/environment`.
