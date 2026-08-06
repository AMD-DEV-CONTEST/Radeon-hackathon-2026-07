"use client";

import type { Vec3 } from "./types";

export default function StreetFurniture({ position }: { position: Vec3 }) {
  return (
    <group position={position}>
      <mesh castShadow position={[0, 1.15, 0]}>
        <cylinderGeometry args={[0.055, 0.075, 2.3, 8]} />
        <meshStandardMaterial color="#29333a" metalness={0.75} roughness={0.3} />
      </mesh>
      <mesh position={[0, 2.35, 0]}>
        <sphereGeometry args={[0.16, 12, 12]} />
        <meshStandardMaterial
          color="#d9fbff"
          emissive="#67e8f9"
          emissiveIntensity={3}
        />
      </mesh>
      <pointLight position={[0, 2.3, 0]} intensity={2.2} distance={6} color="#8be9ff" />
    </group>
  );
}
