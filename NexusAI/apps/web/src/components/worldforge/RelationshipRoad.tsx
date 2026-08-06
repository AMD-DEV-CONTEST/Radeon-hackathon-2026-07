"use client";

import { Html } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import type { WorldForgeRelationship } from "@/lib/api";
import type { Vec3 } from "./types";

type Props = {
  relationship: WorldForgeRelationship;
  source: Vec3;
  target: Vec3;
  highlighted?: boolean;
  dimmed?: boolean;
};

function relationshipLabel(type: string): string {
  return type.replaceAll("_", " ").toUpperCase();
}

function relationshipStyle(type: string) {
  const normalized = type.toUpperCase();

  switch (normalized) {
    case "LIVES_IN":
    case "LOCATED_IN":
    case "BASED_IN":
      return {
        color: "#34d399",
        width: 0.075,
      };

    case "WORKS_WITH":
    case "WORKS_AT":
    case "WORKS_IN":
      return {
        color: "#facc15",
        width: 0.065,
      };

    case "CREATED":
    case "MAINTAINS":
    case "LEADS":
      return {
        color: "#f0abfc",
        width: 0.07,
      };

    case "ADVISES":
      return {
        color: "#c4b5fd",
        width: 0.06,
      };

    case "CONNECTED_TO":
    case "CONTAINS":
      return {
        color: "#22d3ee",
        width: 0.06,
      };

    case "VISITED":
      return {
        color: "#60a5fa",
        width: 0.05,
      };

    default:
      return {
        color: "#94a3b8",
        width: 0.05,
      };
  }
}

export default function RelationshipRoad({
  relationship,
  source,
  target,
  highlighted = false,
  dimmed = false,
}: Props) {
  const style = relationshipStyle(relationship.relationship_type);

  const geometry = useMemo(() => {
    const start = new THREE.Vector3(source[0], 0.09, source[2]);

    const end = new THREE.Vector3(target[0], 0.09, target[2]);

    const midpoint = start.clone().add(end).multiplyScalar(0.5);

    const direction = end.clone().sub(start);
    const length = direction.length();

    const quaternion = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      direction.clone().normalize(),
    );

    return {
      midpoint,
      quaternion,
      length,
    };
  }, [source, target]);

  const opacity = dimmed ? 0.06 : highlighted ? 0.95 : 0.38;

  return (
    <group>
      {/* Relationship road */}
      <mesh position={geometry.midpoint} quaternion={geometry.quaternion}>
        <cylinderGeometry
          args={[
            highlighted ? style.width * 1.8 : style.width,
            highlighted ? style.width * 1.8 : style.width,
            geometry.length,
            8,
          ]}
        />

        <meshBasicMaterial
          color={style.color}
          transparent
          opacity={opacity}
          depthWrite={false}
        />
      </mesh>

      {/* Highlight glow */}
      {highlighted && !dimmed && (
        <mesh position={geometry.midpoint} quaternion={geometry.quaternion}>
          <cylinderGeometry
            args={[style.width * 4, style.width * 4, geometry.length, 8]}
          />

          <meshBasicMaterial
            color={style.color}
            transparent
            opacity={0.08}
            depthWrite={false}
          />
        </mesh>
      )}

      {/* Relationship label */}
      {highlighted && !dimmed && (
        <Html
          position={[geometry.midpoint.x, 0.42, geometry.midpoint.z]}
          center
          distanceFactor={14}
          zIndexRange={[10, 0]}
        >
          <div className="pointer-events-none whitespace-nowrap rounded-md border border-white/10 bg-black/80 px-2 py-1 text-[8px] font-semibold tracking-[0.15em] text-white/70 backdrop-blur-md">
            {relationshipLabel(relationship.relationship_type)}
          </div>
        </Html>
      )}
    </group>
  );
}
