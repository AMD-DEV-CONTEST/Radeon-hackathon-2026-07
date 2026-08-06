export type TerrainTextureSet = {
  albedo?: string;
  normal?: string;
  roughness?: string;
  ao?: string;
  displacement?: string;
};

export type TerrainMaterialProfile = {
  baseColor: string;
  roughness: number;
  metalness: number;
  normalScale: number;
  displacementScale: number;
  repeat: number;
  textures: TerrainTextureSet;
};

const root = "/worldforge/assets/terrain";

export const TERRAIN_MATERIAL_PROFILES: Record<string, TerrainMaterialProfile> = {
  desert: {
    baseColor: "#a97948", roughness: 0.98, metalness: 0, normalScale: 0.7,
    displacementScale: 0.18, repeat: 12,
    textures: {
      albedo: `${root}/desert/albedo.jpg`, normal: `${root}/desert/normal.jpg`,
      roughness: `${root}/desert/roughness.jpg`, ao: `${root}/desert/ao.jpg`,
    },
  },
  arctic: {
    baseColor: "#dce8ec", roughness: 0.82, metalness: 0.02, normalScale: 0.45,
    displacementScale: 0.1, repeat: 10,
    textures: {
      albedo: `${root}/arctic/albedo.jpg`, normal: `${root}/arctic/normal.jpg`,
      roughness: `${root}/arctic/roughness.jpg`, ao: `${root}/arctic/ao.jpg`,
    },
  },
  forest: {
    baseColor: "#304633", roughness: 0.96, metalness: 0, normalScale: 0.9,
    displacementScale: 0.15, repeat: 14,
    textures: {
      albedo: `${root}/forest/albedo.jpg`, normal: `${root}/forest/normal.jpg`,
      roughness: `${root}/forest/roughness.jpg`, ao: `${root}/forest/ao.jpg`,
    },
  },
  grassland: {
    baseColor: "#586f3c", roughness: 0.94, metalness: 0, normalScale: 0.65,
    displacementScale: 0.12, repeat: 14,
    textures: {
      albedo: `${root}/grassland/albedo.jpg`, normal: `${root}/grassland/normal.jpg`,
      roughness: `${root}/grassland/roughness.jpg`, ao: `${root}/grassland/ao.jpg`,
    },
  },
  urban: {
    baseColor: "#424548", roughness: 0.78, metalness: 0.08, normalScale: 0.5,
    displacementScale: 0.04, repeat: 18,
    textures: {
      albedo: `${root}/urban/albedo.jpg`, normal: `${root}/urban/normal.jpg`,
      roughness: `${root}/urban/roughness.jpg`, ao: `${root}/urban/ao.jpg`,
    },
  },
  mountain: {
    baseColor: "#686a65", roughness: 0.9, metalness: 0.01, normalScale: 1.15,
    displacementScale: 0.22, repeat: 11,
    textures: {
      albedo: `${root}/mountain/albedo.jpg`, normal: `${root}/mountain/normal.jpg`,
      roughness: `${root}/mountain/roughness.jpg`, ao: `${root}/mountain/ao.jpg`,
    },
  },
  coastal: {
    baseColor: "#9c8967", roughness: 0.91, metalness: 0, normalScale: 0.65,
    displacementScale: 0.12, repeat: 13,
    textures: {
      albedo: `${root}/coastal/albedo.jpg`, normal: `${root}/coastal/normal.jpg`,
      roughness: `${root}/coastal/roughness.jpg`, ao: `${root}/coastal/ao.jpg`,
    },
  },
  generic: {
    baseColor: "#505a4e", roughness: 0.94, metalness: 0, normalScale: 0.65,
    displacementScale: 0.1, repeat: 12, textures: {},
  },
};

export function terrainMaterialProfile(biome?: string) {
  return TERRAIN_MATERIAL_PROFILES[biome ?? "generic"] ?? TERRAIN_MATERIAL_PROFILES.generic;
}
