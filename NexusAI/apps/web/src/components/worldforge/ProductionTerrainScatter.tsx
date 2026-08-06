"use client";

import { useMemo } from "react";
import EnvironmentAssetLOD from "./EnvironmentAssetLOD";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import { productionAssetsForBiome } from "./environmentAssetManifest";
import { terrainHeightAt } from "./terrainHeight";
import { enforceBiomeBudget } from "./productionAssetBudget";

function seeded(seed: number) {
  const x = Math.sin(seed * 9283.17) * 43758.5453123;
  return x - Math.floor(x);
}

export default function ProductionTerrainScatter({
  spec,
}: {
  spec: EnvironmentRenderSpec | null;
}) {
  const biome = spec?.biome ?? "generic";
  const placements = useMemo(() => {
    const assets = productionAssetsForBiome(biome);
    const budgetedAssets = enforceBiomeBudget(assets);

    return budgetedAssets.flatMap(({ asset, count }, assetIndex) =>
      Array.from({ length: count }, (_, index) => {
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
          position: [x, terrainHeightAt(x, z, biome) + 0.02, z] as [
            number,
            number,
            number,
          ],
          rotation: seeded(seed + 3) * Math.PI * 2,
          scale:
            asset.scale[0] +
            seeded(seed + 2) * (asset.scale[1] - asset.scale[0]),
        };
      }),
    );
  }, [biome]);

  // No production files yet? Keep the Gen-7 scatter rather than requesting missing GLBs.
  if (placements.length === 0) return null;

  return (
    <group>
      {placements.map((item) => (
        <group
          key={item.key}
          position={item.position}
          rotation={[0, item.rotation, 0]}
        >
          <EnvironmentAssetLOD asset={item.asset} scale={item.scale} />
        </group>
      ))}
    </group>
  );
}
