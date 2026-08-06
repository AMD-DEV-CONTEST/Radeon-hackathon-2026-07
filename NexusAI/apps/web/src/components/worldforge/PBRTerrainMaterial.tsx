"use client";

import * as THREE from "three";
import { terrainMaterialProfile } from "./terrainMaterialProfiles";
import { useTerrainTextures } from "./useTerrainTextures";

export default function PBRTerrainMaterial({ biome }: { biome: string }) {
  const profile = terrainMaterialProfile(biome);
  const maps = useTerrainTextures(profile);

  return (
    <meshStandardMaterial
      color={maps.map ? "#ffffff" : profile.baseColor}
      map={maps.map}
      normalMap={maps.normalMap}
      normalScale={new THREE.Vector2(profile.normalScale, profile.normalScale)}
      roughness={profile.roughness}
      roughnessMap={maps.roughnessMap}
      aoMap={maps.aoMap}
      aoMapIntensity={0.75}
      metalness={profile.metalness}
    />
  );
}
