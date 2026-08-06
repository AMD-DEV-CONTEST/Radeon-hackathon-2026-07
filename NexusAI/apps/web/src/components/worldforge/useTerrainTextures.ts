"use client";

import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import type { TerrainMaterialProfile } from "./terrainMaterialProfiles";

type Maps = {
  map?: THREE.Texture;
  normalMap?: THREE.Texture;
  roughnessMap?: THREE.Texture;
  aoMap?: THREE.Texture;
};

function prepare(texture: THREE.Texture, repeat: number, srgb = false) {
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeat, repeat);
  texture.anisotropy = 8;
  if (srgb) texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

export function useTerrainTextures(profile: TerrainMaterialProfile): Maps {
  const [maps, setMaps] = useState<Maps>({});

  const signature = useMemo(
    () => JSON.stringify([profile.repeat, profile.textures]),
    [profile],
  );

  useEffect(() => {
    let cancelled = false;
    const loader = new THREE.TextureLoader();
    const loaded: THREE.Texture[] = [];

    const load = (
      url: string | undefined,
      srgb = false,
    ): Promise<THREE.Texture | undefined> =>
      !url
        ? Promise.resolve(undefined)
        : new Promise((resolve) => {
            loader.load(
              url,
              (texture) => {
                loaded.push(texture);
                resolve(prepare(texture, profile.repeat, srgb));
              },
              undefined,
              () => resolve(undefined),
            );
          });

    Promise.all([
      load(profile.textures.albedo, true),
      load(profile.textures.normal),
      load(profile.textures.roughness),
      load(profile.textures.ao),
    ]).then(([map, normalMap, roughnessMap, aoMap]) => {
      if (!cancelled) setMaps({ map, normalMap, roughnessMap, aoMap });
    });

    return () => {
      cancelled = true;
      loaded.forEach((texture) => texture.dispose());
    };
  }, [signature, profile]);

  return maps;
}
