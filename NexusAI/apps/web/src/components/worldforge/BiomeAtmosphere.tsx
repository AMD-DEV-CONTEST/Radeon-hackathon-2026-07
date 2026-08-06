"use client";

import { Sparkles } from "@react-three/drei";
import type { EnvironmentRenderSpec } from "./environmentTypes";

export default function BiomeAtmosphere({ spec }: { spec: EnvironmentRenderSpec | null }) {
  if (!spec) return null;
  const snow = spec.weather_effects.includes("snowfall");
  const dust = spec.atmosphere.includes("dust_haze") || spec.weather_effects.includes("sand_gusts");

  if (snow) {
    return <Sparkles count={240} scale={[72, 24, 72]} size={2.2} speed={0.28} opacity={0.55} />;
  }
  if (dust) {
    return <Sparkles count={120} scale={[72, 12, 72]} size={1.2} speed={0.12} opacity={0.22} />;
  }
  return null;
}
