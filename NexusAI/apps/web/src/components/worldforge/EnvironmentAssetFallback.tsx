"use client";

import type { ProductionEnvironmentAsset } from "./environmentAssetManifest";

export default function EnvironmentAssetFallback({
  asset,
  scale,
}: {
  asset: ProductionEnvironmentAsset;
  scale: number;
}) {
  if (asset.kind === "vegetation") {
    return (
      <group scale={scale}>
        <mesh castShadow position={[0, 0.85, 0]}>
          <cylinderGeometry args={[0.1, 0.16, 1.7, 7]} />
          <meshStandardMaterial color="#49372a" roughness={1} />
        </mesh>
        <mesh castShadow position={[0, 1.9, 0]}>
          <coneGeometry args={[0.8, 2.1, 9]} />
          <meshStandardMaterial color="#304c35" roughness={0.98} />
        </mesh>
      </group>
    );
  }
  return (
    <mesh castShadow receiveShadow scale={[scale, scale * 0.72, scale]}>
      <dodecahedronGeometry args={[0.7, 1]} />
      <meshStandardMaterial color="#66645f" roughness={0.98} />
    </mesh>
  );
}
