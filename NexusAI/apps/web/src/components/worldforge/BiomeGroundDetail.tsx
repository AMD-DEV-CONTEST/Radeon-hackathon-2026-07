"use client";

import { useMemo } from "react";
import type { EnvironmentRenderSpec } from "./environmentTypes";

const DETAIL: Record<string, { color: string; count: number }> = {
  desert: { color: "#75502f", count: 45 },
  arctic: { color: "#c5d7df", count: 35 },
  forest: { color: "#1f3326", count: 70 },
  grassland: { color: "#40572e", count: 55 },
  mountain: { color: "#51534f", count: 55 },
  coastal: { color: "#776b54", count: 42 },
  urban: { color: "#2f3235", count: 20 },
  generic: { color: "#414a40", count: 35 },
};

function seeded(seed: number) {
  const x = Math.sin(seed * 517.73) * 13758.5453;
  return x - Math.floor(x);
}

export default function BiomeGroundDetail({
  spec,
}: {
  spec: EnvironmentRenderSpec | null;
}) {
  const biome = spec?.biome ?? "generic";
  const config = DETAIL[biome] ?? DETAIL.generic;
  const patches = useMemo(
    () =>
      Array.from({ length: config.count }, (_, i) => {
        const angle = seeded(i + 11) * Math.PI * 2;
        const radius = 7 + seeded(i + 12) * 39;
        return {
          x: Math.cos(angle) * radius,
          z: Math.sin(angle) * radius,
          scale: 0.5 + seeded(i + 13) * 2.4,
          rotation: seeded(i + 14) * Math.PI,
        };
      }),
    [config.count],
  );

  return (
    <group>
      {patches.map((patch, index) => (
        <mesh
          key={index}
          rotation={[-Math.PI / 2, 0, patch.rotation]}
          position={[patch.x, 0.006, patch.z]}
          receiveShadow
        >
          <circleGeometry args={[patch.scale, 10]} />
          <meshStandardMaterial
            color={config.color}
            roughness={1}
            transparent
            opacity={0.28}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}
