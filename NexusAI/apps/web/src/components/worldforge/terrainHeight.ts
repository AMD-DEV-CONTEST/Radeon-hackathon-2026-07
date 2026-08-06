import { fbm } from "./terrainNoise";
import { terrainProfile } from "./terrainProfiles";

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v));
}

function smooth01(v: number) {
  const t = clamp01(v);
  return t * t * (3 - 2 * t);
}

function settlementMask(x: number, z: number, radius: number) {
  const distance = Math.hypot(x, z);
  return smooth01((distance - radius * 0.55) / (radius * 0.65));
}

function roadMask(x: number, z: number, width: number) {
  const nearestAxis = Math.min(Math.abs(x), Math.abs(z));
  return smooth01((nearestAxis - width) / (width * 1.4));
}

export function terrainHeightAt(
  x: number,
  z: number,
  biome = "generic",
  seed = 17,
): number {
  const profile = terrainProfile(biome);
  const base = fbm(
    x * profile.frequency,
    z * profile.frequency,
    seed,
    profile.octaves,
  );

  let height = base * profile.amplitude;

  if (biome === "desert") {
    height += Math.sin(x * 0.13 + z * 0.055) * 0.7;
  } else if (biome === "mountain") {
    height += Math.abs(fbm(x * 0.018, z * 0.018, seed + 91, 3)) * profile.ridgeStrength * 3.5;
  } else if (biome === "coastal") {
    height += Math.max(0, (z + 24) * 0.025);
  } else if (biome === "arctic") {
    height += Math.abs(Math.sin(x * 0.055) * Math.cos(z * 0.04)) * 0.55;
  }

  // Keep the city center and principal cross-roads navigable.
  height *= settlementMask(x, z, profile.settlementRadius);
  height *= 0.35 + roadMask(x, z, profile.pathWidth) * 0.65;

  return height;
}
