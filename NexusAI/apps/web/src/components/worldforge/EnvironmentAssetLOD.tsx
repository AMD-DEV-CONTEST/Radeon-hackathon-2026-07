"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { Suspense, useRef, useState } from "react";
import * as THREE from "three";

import type { ProductionEnvironmentAsset } from "./environmentAssetManifest";
import EnvironmentAsset from "./EnvironmentAsset";
import EnvironmentAssetFallback from "./EnvironmentAssetFallback";

type LodLevel = "production" | "fallback" | "hidden";

export default function EnvironmentAssetLOD({
  asset,
  scale,
}: {
  asset: ProductionEnvironmentAsset;
  scale: number;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const { camera } = useThree();
  const [lodLevel, setLodLevel] = useState<LodLevel>("production");
  const lastLevel = useRef<LodLevel>("production");
  const worldPosition = useRef(new THREE.Vector3());
  useFrame(() => {
    const group = groupRef.current;
    if (!group) return;

    group.getWorldPosition(worldPosition.current);

    const distance = camera.position.distanceTo(worldPosition.current);
    let nextLevel: LodLevel;

    if (distance <= asset.lodDistance) {
      nextLevel = "production";
    } else if (distance <= asset.lodDistance * 1.75) {
      nextLevel = "fallback";
    } else {
      nextLevel = "hidden";
    }

    if (nextLevel !== lastLevel.current) {
      lastLevel.current = nextLevel;
      setLodLevel(nextLevel);
    }
  });

  return (
    <group ref={groupRef}>
      {lodLevel === "production" && (
        <Suspense
          fallback={<EnvironmentAssetFallback asset={asset} scale={scale} />}
        >
          <EnvironmentAsset asset={asset} scale={scale} />
        </Suspense>
      )}

      {lodLevel === "fallback" && (
        <EnvironmentAssetFallback asset={asset} scale={scale} />
      )}
    </group>
  );
}
