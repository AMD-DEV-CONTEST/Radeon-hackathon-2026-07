"use client";

import { Clone, useGLTF } from "@react-three/drei";

export default function HumanModel({
  url,
  scale = 1,
}: {
  url: string;
  scale?: number;
}) {
  const gltf = useGLTF(url);
  return <Clone object={gltf.scene} scale={scale} castShadow receiveShadow />;
}
