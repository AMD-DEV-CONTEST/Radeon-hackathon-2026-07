"use client";

import type { CharacterProfile } from "./characterTypes";

export default function ProceduralHuman({
  profile,
  selected = false,
  dimmed = false,
}: {
  profile: CharacterProfile;
  selected?: boolean;
  dimmed?: boolean;
}) {
  const opacity = dimmed ? 0.3 : 1;
  const s = profile.height;
  const build = profile.build;

  return (
    <group scale={[build, s, build]}>
      {/* legs */}
      {[-0.12, 0.12].map((x) => (
        <mesh key={x} castShadow position={[x, 0.46, 0]}>
          <capsuleGeometry args={[0.085, 0.58, 6, 10]} />
          <meshStandardMaterial color={profile.lowerColor} roughness={0.9} transparent opacity={opacity} />
        </mesh>
      ))}
      {/* shoes */}
      {[-0.12, 0.12].map((x) => (
        <mesh key={`shoe-${x}`} castShadow position={[x, 0.1, 0.045]} scale={[1, 0.65, 1.45]}>
          <sphereGeometry args={[0.11, 12, 10]} />
          <meshStandardMaterial color="#171717" roughness={0.95} transparent opacity={opacity} />
        </mesh>
      ))}
      {/* torso */}
      <mesh castShadow position={[0, 1.18, 0]}>
        <capsuleGeometry args={[0.27, 0.55, 8, 14]} />
        <meshStandardMaterial color={profile.upperColor} roughness={0.82} transparent opacity={opacity} />
      </mesh>
      {/* arms */}
      {[-1, 1].map((side) => (
        <mesh key={side} castShadow position={[side * 0.34, 1.15, 0]} rotation={[0, 0, side * 0.08]}>
          <capsuleGeometry args={[0.07, 0.58, 6, 10]} />
          <meshStandardMaterial color={profile.upperColor} roughness={0.86} transparent opacity={opacity} />
        </mesh>
      ))}
      {/* neck */}
      <mesh castShadow position={[0, 1.61, 0]}>
        <cylinderGeometry args={[0.09, 0.1, 0.16, 12]} />
        <meshStandardMaterial color={profile.skinTone} roughness={0.92} transparent opacity={opacity} />
      </mesh>
      {/* head */}
      <mesh castShadow position={[0, 1.84, 0]} scale={[0.92, 1.08, 0.92]}>
        <sphereGeometry args={[0.205, 20, 18]} />
        <meshStandardMaterial color={profile.skinTone} roughness={0.92} transparent opacity={opacity} />
      </mesh>
      {/* hair */}
      <mesh castShadow position={[0, 1.98, -0.01]} scale={[1, 0.5, 1]}>
        <sphereGeometry args={[0.215, 16, 12]} />
        <meshStandardMaterial color={profile.hairColor} roughness={1} transparent opacity={opacity} />
      </mesh>
      {/* contextual clothing accent */}
      <mesh castShadow position={[0, 1.43, 0.235]}>
        <boxGeometry args={[0.32, 0.1, 0.035]} />
        <meshStandardMaterial color={profile.accentColor} roughness={0.8} transparent opacity={opacity} />
      </mesh>
      {selected && <pointLight position={[0, 1.4, 0]} intensity={2.2} distance={3.5} color="#fde68a" />}
    </group>
  );
}
