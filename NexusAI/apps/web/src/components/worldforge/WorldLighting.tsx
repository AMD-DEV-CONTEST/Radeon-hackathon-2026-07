"use client";

import { Environment } from "@react-three/drei";

export default function WorldLighting() {
  return (
    <>
      <ambientLight intensity={0.34} />
      <hemisphereLight args={["#9bd8ff", "#08120e", 0.7]} />
      <directionalLight
        castShadow
        position={[18, 28, 12]}
        intensity={2.4}
        color="#d9efff"
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={90}
        shadow-camera-left={-40}
        shadow-camera-right={40}
        shadow-camera-top={40}
        shadow-camera-bottom={-40}
      />
      <directionalLight position={[-22, 10, -18]} intensity={0.55} color="#7dd3fc" />
      <fog attach="fog" args={["#020609", 48, 105]} />
      <Environment preset="night" />
    </>
  );
}
