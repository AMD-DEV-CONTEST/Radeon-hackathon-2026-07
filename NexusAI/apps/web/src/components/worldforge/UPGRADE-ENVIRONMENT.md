# WorldForge Environment Upgrade

Place all files in:

apps/web/src/components/worldforge/

This package was generated from the current WorldForge folder you uploaded.

## New components
- WorldTerrain.tsx
- WorldLighting.tsx
- DistrictEnvironment.tsx
- StreetFurniture.tsx

## Updated
- KnowledgeCity.tsx
- KnowledgeDistrict.tsx

All other files are preserved from the uploaded version so this can be used as a full folder replacement.

## Verify
From apps/web:
npm run build

Then:
npm run dev

Keep the FastAPI backend running on port 8000.
