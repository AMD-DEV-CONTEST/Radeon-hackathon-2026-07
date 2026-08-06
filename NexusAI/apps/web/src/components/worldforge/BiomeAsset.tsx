"use client";

import { Clone, useGLTF } from "@react-three/drei";
import type { BiomeAssetDefinition } from "./BiomeAssetRegistry";

function LoadedBiomeAsset({
  url,
  scale,
}: {
  url: string;
  scale: number;
}) {
  const gltf = useGLTF(url);
  return <Clone object={gltf.scene} scale={scale} castShadow receiveShadow />;
}

function PrimitiveBiomeAsset({
  asset,
  scale,
}: {
  asset: BiomeAssetDefinition;
  scale: number;
}) {
  if (asset.kind === "vegetation") {
    return (
      <group scale={scale}>
        <mesh castShadow position={[0, 0.8, 0]}>
          <cylinderGeometry args={[0.11, 0.16, 1.6, 7]} />
          <meshStandardMaterial color="#4a3728" roughness={1} />
        </mesh>
        <mesh castShadow position={[0, 1.75, 0]}>
          <coneGeometry args={[0.72, 1.9, 8]} />
          <meshStandardMaterial color="#314d35" roughness={0.96} />
        </mesh>
      </group>
    );
  }

  return (
    <mesh castShadow receiveShadow scale={[scale, scale * 0.72, scale]}>
      <dodecahedronGeometry args={[0.65, 0]} />
      <meshStandardMaterial color="#6d6a61" roughness={0.98} />
    </mesh>
  );
}

export default function BiomeAsset({
  asset,
  scale,
}: {
  asset: BiomeAssetDefinition;
  scale: number;
}) {
  return asset.url ? (
    <LoadedBiomeAsset url={asset.url} scale={scale} />
  ) : (
    <PrimitiveBiomeAsset asset={asset} scale={scale} />
  );
}
