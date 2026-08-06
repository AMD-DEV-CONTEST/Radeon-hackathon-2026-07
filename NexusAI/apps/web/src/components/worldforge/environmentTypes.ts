export type EnvironmentRenderSpec = {
  biome: string;
  time_of_day: "dawn" | "day" | "dusk" | "night";
  terrain_materials: string[];
  terrain_features: string[];
  vegetation_assets: string[];
  prop_assets: string[];
  architecture_materials: string[];
  atmosphere: string[];
  weather_effects: string[];
  character_context: string;
  asset_families: string[];
  lighting: {
    preset: string;
    sun_intensity: number;
    ambient_intensity: number;
    fog_density: number;
  };
};
