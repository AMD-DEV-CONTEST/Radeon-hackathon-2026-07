export type TerrainProfile = {
  amplitude: number;
  frequency: number;
  octaves: number;
  settlementRadius: number;
  pathWidth: number;
  ridgeStrength: number;
};

export const TERRAIN_PROFILES: Record<string, TerrainProfile> = {
  desert: { amplitude: 3.2, frequency: 0.045, octaves: 3, settlementRadius: 16, pathWidth: 3.5, ridgeStrength: 0.5 },
  arctic: { amplitude: 2.4, frequency: 0.038, octaves: 4, settlementRadius: 15, pathWidth: 3.2, ridgeStrength: 0.7 },
  forest: { amplitude: 2.7, frequency: 0.035, octaves: 5, settlementRadius: 16, pathWidth: 3.0, ridgeStrength: 0.45 },
  grassland: { amplitude: 1.8, frequency: 0.028, octaves: 4, settlementRadius: 18, pathWidth: 3.4, ridgeStrength: 0.2 },
  urban: { amplitude: 0.45, frequency: 0.025, octaves: 3, settlementRadius: 24, pathWidth: 4.2, ridgeStrength: 0.05 },
  mountain: { amplitude: 8.0, frequency: 0.032, octaves: 5, settlementRadius: 14, pathWidth: 3.2, ridgeStrength: 1.5 },
  coastal: { amplitude: 2.2, frequency: 0.032, octaves: 4, settlementRadius: 17, pathWidth: 3.5, ridgeStrength: 0.35 },
  generic: { amplitude: 1.6, frequency: 0.03, octaves: 4, settlementRadius: 17, pathWidth: 3.3, ridgeStrength: 0.25 },
};

export function terrainProfile(biome?: string): TerrainProfile {
  return TERRAIN_PROFILES[biome ?? "generic"] ?? TERRAIN_PROFILES.generic;
}
