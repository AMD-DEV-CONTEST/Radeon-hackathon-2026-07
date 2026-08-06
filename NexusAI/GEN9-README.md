# NexusAI Production Environment Assets — Generation 9

Built against the uploaded post-Generation-8 source.

This generation establishes the production GLB asset manifest, renderer, safe fallback, opt-in runtime switch, biome asset directories, and WorldForge integration.

It intentionally does NOT bundle arbitrary third-party binaries. Populate the manifest paths with chosen licensed assets before enabling:
NEXT_PUBLIC_WORLDFORGE_PRODUCTION_ASSETS=true

Build:
cd apps/web
npm run build
