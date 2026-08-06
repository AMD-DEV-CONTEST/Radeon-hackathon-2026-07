import type { EnvironmentRenderSpec } from "./environmentTypes";

export type BiomeAssetKind =
  | "rock"
  | "vegetation"
  | "prop"
  | "landmark";

export type BiomeAssetDefinition = {
  id: string;
  kind: BiomeAssetKind;
  biomes: string[];
  url?: string;
  scale: [number, number];
  density: number;
  minRadius: number;
  maxRadius: number;
};

const DEFINITIONS: BiomeAssetDefinition[] = [
  { id: "desert-rock", kind: "rock", biomes: ["desert"], scale: [0.8, 2.4], density: 18, minRadius: 8, maxRadius: 44 },
  { id: "desert-shrub", kind: "vegetation", biomes: ["desert"], scale: [0.5, 1.2], density: 16, minRadius: 9, maxRadius: 43 },
  { id: "snow-pine", kind: "vegetation", biomes: ["arctic"], scale: [1.0, 2.0], density: 20, minRadius: 10, maxRadius: 44 },
  { id: "ice-rock", kind: "rock", biomes: ["arctic"], scale: [0.7, 2.2], density: 16, minRadius: 8, maxRadius: 44 },
  { id: "forest-tree", kind: "vegetation", biomes: ["forest"], scale: [1.2, 2.6], density: 42, minRadius: 8, maxRadius: 45 },
  { id: "forest-rock", kind: "rock", biomes: ["forest"], scale: [0.6, 1.7], density: 15, minRadius: 8, maxRadius: 42 },
  { id: "grass-tree", kind: "vegetation", biomes: ["grassland"], scale: [1.0, 2.2], density: 14, minRadius: 12, maxRadius: 44 },
  { id: "field-rock", kind: "rock", biomes: ["grassland"], scale: [0.5, 1.4], density: 12, minRadius: 8, maxRadius: 44 },
  { id: "mountain-pine", kind: "vegetation", biomes: ["mountain"], scale: [0.9, 2.0], density: 18, minRadius: 10, maxRadius: 44 },
  { id: "mountain-boulder", kind: "rock", biomes: ["mountain"], scale: [1.0, 3.2], density: 28, minRadius: 8, maxRadius: 45 },
  { id: "coastal-palm", kind: "vegetation", biomes: ["coastal"], scale: [1.0, 2.0], density: 14, minRadius: 12, maxRadius: 43 },
  { id: "coastal-rock", kind: "rock", biomes: ["coastal"], scale: [0.7, 2.0], density: 20, minRadius: 8, maxRadius: 44 },
  { id: "urban-tree", kind: "vegetation", biomes: ["urban"], scale: [0.9, 1.5], density: 10, minRadius: 12, maxRadius: 42 },
  { id: "generic-tree", kind: "vegetation", biomes: ["generic"], scale: [0.8, 1.8], density: 16, minRadius: 10, maxRadius: 44 },
  { id: "generic-rock", kind: "rock", biomes: ["generic"], scale: [0.6, 1.6], density: 12, minRadius: 8, maxRadius: 44 },
];

export function resolveBiomeAssets(
  spec: EnvironmentRenderSpec | null,
): BiomeAssetDefinition[] {
  const biome = spec?.biome ?? "generic";
  const exact = DEFINITIONS.filter((asset) => asset.biomes.includes(biome));
  return exact.length
    ? exact
    : DEFINITIONS.filter((asset) => asset.biomes.includes("generic"));
}
