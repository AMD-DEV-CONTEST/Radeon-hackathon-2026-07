"use client";

import { useMemo } from "react";
import * as THREE from "three";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import { terrainHeightAt } from "./terrainHeight";
import PBRTerrainMaterial from "./PBRTerrainMaterial";

export default function BiomeTerrain({
  spec,
  size = 96,
}: {
  spec: EnvironmentRenderSpec | null;
  size?: number;
}) {
  const biome = spec?.biome ?? "generic";

  const geometry = useMemo(() => {
    const segments = 96;
    const geo = new THREE.PlaneGeometry(size, size, segments, segments);
    const positions = geo.attributes.position;

    for (let i = 0; i < positions.count; i += 1) {
      const x = positions.getX(i);
      const localY = positions.getY(i);
      positions.setZ(i, terrainHeightAt(x, -localY, biome));
    }

    positions.needsUpdate = true;
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    return geo;
  }, [biome, size]);

  return (
    <mesh
      geometry={geometry}
      rotation={[-Math.PI / 2, 0, 0]}
      receiveShadow
      position={[0, -0.04, 0]}
    >
      <PBRTerrainMaterial biome={biome} />
    </mesh>
  );
}
