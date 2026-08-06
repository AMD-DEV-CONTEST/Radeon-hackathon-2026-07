"use client";

import { Environment, Stars } from "@react-three/drei";
import type { EnvironmentRenderSpec } from "./environmentTypes";

const PALETTE: Record<
  string,
  { sky: string; ground: string; fog: string; hemi: string }
> = {
  desert: {
    sky: "#c88f5a",
    ground: "#8a5a32",
    fog: "#c79a6b",
    hemi: "#f3c98b",
  },
  arctic: {
    sky: "#b9d8e8",
    ground: "#d8e4e8",
    fog: "#d6e7ef",
    hemi: "#eaf8ff",
  },
  forest: {
    sky: "#496b5b",
    ground: "#253b2d",
    fog: "#536b5c",
    hemi: "#b7d7b1",
  },
  grassland: {
    sky: "#8bb7c9",
    ground: "#4f6338",
    fog: "#9db7a0",
    hemi: "#d8e6bd",
  },
  urban: {
    sky: "#73808b",
    ground: "#34383c",
    fog: "#727b82",
    hemi: "#c9d4dc",
  },
  mountain: {
    sky: "#8da8ba",
    ground: "#5d625f",
    fog: "#9ca9ae",
    hemi: "#dce6e8",
  },
  coastal: {
    sky: "#78aeca",
    ground: "#8a8067",
    fog: "#a7c4cf",
    hemi: "#d8eff5",
  },
  generic: {
    sky: "#718493",
    ground: "#4d554c",
    fog: "#7c8986",
    hemi: "#d5dfd8",
  },
};

const TEMPORAL = {
  dawn: {
    sky: "#d58a78",
    fog: "#a77d78",
    hemi: "#ffd6b3",
    sun: "#ffcc9a",
    sunMultiplier: 0.65,
    ambientMultiplier: 0.75,
  },
  day: null,
  dusk: {
    sky: "#493d62",
    fog: "#66566c",
    hemi: "#d6a5a5",
    sun: "#ff9b73",
    sunMultiplier: 0.5,
    ambientMultiplier: 0.62,
  },
  night: {
    sky: "#020611",
    fog: "#07111b",
    hemi: "#263859",
    sun: "#9dbfff",
    sunMultiplier: 0.18,
    ambientMultiplier: 0.3,
  },
} as const;

export default function BiomeEnvironment({
  spec,
}: {
  spec: EnvironmentRenderSpec | null;
}) {
  const biome = spec?.biome ?? "generic";
  const timeOfDay = spec?.time_of_day ?? "day";

  const palette = PALETTE[biome] ?? PALETTE.generic;
  const temporal = TEMPORAL[timeOfDay];
  const lighting = spec?.lighting;

  const sky = temporal?.sky ?? palette.sky;
  const fog = temporal?.fog ?? palette.fog;
  const hemi = temporal?.hemi ?? palette.hemi;

  const sunIntensity =
    (lighting?.sun_intensity ?? 0.95) * (temporal?.sunMultiplier ?? 1);

  const ambientIntensity =
    (lighting?.ambient_intensity ?? 0.52) * (temporal?.ambientMultiplier ?? 1);

  const sunColor =
    temporal?.sun ?? (biome === "desert" ? "#ffe0a3" : "#f2f7ff");

  const isNight = timeOfDay === "night";
  console.log("[WorldForge Environment]", {
    biome,
    timeOfDay,
    lighting,
    temporal,
  });
  return (
    <>
      <color attach="background" args={[sky]} />

      <fogExp2 attach="fog" args={[fog, lighting?.fog_density ?? 0.008]} />

      <ambientLight intensity={ambientIntensity} />

      <hemisphereLight args={[hemi, palette.ground, isNight ? 0.28 : 0.72]} />

      <directionalLight
        castShadow
        position={[24, 34, 16]}
        intensity={sunIntensity}
        color={sunColor}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={110}
        shadow-camera-left={-48}
        shadow-camera-right={48}
        shadow-camera-top={48}
        shadow-camera-bottom={-48}
      />

      {isNight && (
        <Stars
          radius={90}
          depth={45}
          count={1800}
          factor={3}
          saturation={0}
          fade
          speed={0.15}
        />
      )}

      <Environment
        preset={isNight ? "night" : biome === "urban" ? "city" : "park"}
      />
    </>
  );
}
