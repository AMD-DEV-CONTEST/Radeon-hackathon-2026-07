"use client";

import { useMemo } from "react";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import { resolveBiomeAssets } from "./BiomeAssetRegistry";
import { terrainHeightAt } from "./terrainHeight";
import BiomeAsset from "./BiomeAsset";

function seeded(seed: number) {
  const x = Math.sin(seed * 9283.17) * 43758.5453123;
  return x - Math.floor(x);
}

export default function TerrainScatter({
  spec,
}: {
  spec: EnvironmentRenderSpec | null;
}) {
  const biome = spec?.biome ?? "generic";

  const placements = useMemo(() => {
    const assets = resolveBiomeAssets(spec);
    return assets.flatMap((asset, assetIndex) =>
      Array.from({ length: asset.density }, (_, index) => {
        const seed = assetIndex * 1000 + index * 31 + 17;
        const angle = seeded(seed) * Math.PI * 2;
        const radius =
          asset.minRadius +
          seeded(seed + 1) * (asset.maxRadius - asset.minRadius);
        const x = Math.cos(angle) * radius;
        const z = Math.sin(angle) * radius;
        return {
          key: `${asset.id}-${index}`,
          asset,
          position: [
            x,
            terrainHeightAt(x, z, biome) + 0.02,
            z,
          ] as [number, number, number],
          rotation: seeded(seed + 3) * Math.PI * 2,
          scale:
            asset.scale[0] +
            seeded(seed + 2) * (asset.scale[1] - asset.scale[0]),
        };
      }),
    );
  }, [spec, biome]);

  return (
    <group>
      {placements.map((item) => (
        <group
          key={item.key}
          position={item.position}
          rotation={[0, item.rotation, 0]}
        >
          <BiomeAsset asset={item.asset} scale={item.scale} />
        </group>
      ))}
    </group>
  );
}
