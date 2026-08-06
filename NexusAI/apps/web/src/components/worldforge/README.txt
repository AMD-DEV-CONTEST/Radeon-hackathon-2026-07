DROP-IN LOCATION:
apps/web/src/components/worldforge/

Replace:
- KnowledgeCity.tsx
- KnowledgeDistrict.tsx

Add:
- EntityStructure.tsx
- PersonEntity.tsx
- PlaceLandmark.tsx
- OrganizationBuilding.tsx
- ProjectBuilding.tsx
- SystemStructure.tsx
- UnknownStructure.tsx
- RelationshipPath.tsx
- EntityInfoPanel.tsx

Keep existing:
- types.ts
- layout.ts
- colors.ts
- utils.ts

WorldForgeScene.tsx must import KnowledgeCity from "./KnowledgeCity" and render <KnowledgeCity data={knowledgeData} /> when knowledgeData exists.
