"use client";

import { Clone, useGLTF } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import type { ProductionEnvironmentAsset } from "./environmentAssetManifest";

export default function EnvironmentAsset({
  asset,
  scale,
}: {
  asset: ProductionEnvironmentAsset;
  scale: number;
}) {
  const gltf = useGLTF(asset.url);

  const normalizationScale = useMemo(() => {
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const size = new THREE.Vector3();

    box.getSize(size);

    if (!Number.isFinite(size.y) || size.y <= 0) {
      return 1;
    }

    return asset.targetHeight / size.y;
  }, [gltf.scene, asset.targetHeight]);

  const finalScale = normalizationScale * scale;

  return (
    <Clone object={gltf.scene} scale={finalScale} castShadow receiveShadow />
  );
}
