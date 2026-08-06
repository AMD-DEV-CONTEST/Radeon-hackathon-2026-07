"use client";

import { Html } from "@react-three/drei";
import type { WorldForgeEntity } from "@/lib/api";

import { ENTITY_COLORS, ENTITY_EMISSIVE } from "./colors";
import type { Vec3 } from "./types";
import { entityKind } from "./utils";

type Props = {
  entity: WorldForgeEntity;
  position: Vec3;
  selected?: boolean;
  dimmed?: boolean;
  onSelect?: (entity: WorldForgeEntity) => void;
};

export default function KnowledgeBuilding({
  entity,
  position,
  selected = false,
  dimmed = false,
  onSelect,
}: Props) {
  const kind = entityKind(entity.entity_type);

  const color = ENTITY_COLORS[kind];
  const emissive = ENTITY_EMISSIVE[kind];

  const importance = Math.min(
    2.2,
    1 + Math.max(entity.connection_count, 0) * 0.14,
  );

  const buildingHeight =
    kind === "ORGANIZATION"
      ? 3.6 * importance
      : kind === "PROJECT" || kind === "SYSTEM"
        ? 2.8 * importance
        : kind === "PERSON"
          ? 1.65 * importance
          : 2.1 * importance;

  const opacity = dimmed ? 0.16 : 1;

  return (
    <group position={position}>
      {/* Ground selection indicator */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.035, 0]}>
          <ringGeometry args={[1.45, 1.7, 48]} />
          <meshBasicMaterial color={color} transparent opacity={0.9} />
        </mesh>
      )}

      {/* PERSON: small home / character residence */}
      {kind === "PERSON" && (
        <group
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entity);
          }}
        >
          <mesh castShadow receiveShadow position={[0, buildingHeight / 2, 0]}>
            <boxGeometry args={[1.7, buildingHeight, 1.7]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={selected ? 1.8 : 0.65}
              transparent
              opacity={opacity}
              roughness={0.58}
              metalness={0.12}
            />
          </mesh>

          <mesh
            castShadow
            position={[0, buildingHeight + 0.5, 0]}
            rotation={[0, Math.PI / 4, 0]}
          >
            <coneGeometry args={[1.45, 1.15, 4]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={selected ? 1.4 : 0.35}
              transparent
              opacity={opacity}
              roughness={0.7}
            />
          </mesh>

          {/* Door */}
          <mesh position={[0, 0.55, 0.861]}>
            <boxGeometry args={[0.38, 0.9, 0.035]} />
            <meshStandardMaterial
              color="#05070b"
              transparent
              opacity={opacity}
            />
          </mesh>
        </group>
      )}

      {/* ORGANIZATION: tower */}
      {kind === "ORGANIZATION" && (
        <group
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entity);
          }}
        >
          <mesh castShadow receiveShadow position={[0, buildingHeight / 2, 0]}>
            <boxGeometry args={[2.25, buildingHeight, 2.25]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={selected ? 1.7 : 0.45}
              transparent
              opacity={opacity}
              roughness={0.24}
              metalness={0.58}
            />
          </mesh>

          {/* Tower crown */}
          <mesh position={[0, buildingHeight + 0.25, 0]}>
            <boxGeometry args={[1.5, 0.5, 1.5]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={1.2}
              transparent
              opacity={opacity}
              metalness={0.65}
              roughness={0.2}
            />
          </mesh>

          {/* Window strips */}
          {[0.8, 1.6, 2.4, 3.2].map((height) =>
            height < buildingHeight ? (
              <mesh key={height} position={[0, height, 1.131]}>
                <boxGeometry args={[1.55, 0.1, 0.025]} />
                <meshBasicMaterial
                  color="#dbeafe"
                  transparent
                  opacity={dimmed ? 0.08 : 0.75}
                />
              </mesh>
            ) : null,
          )}
        </group>
      )}

      {/* PROJECT / SYSTEM: research facility */}
      {(kind === "PROJECT" || kind === "SYSTEM") && (
        <group
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entity);
          }}
        >
          <mesh castShadow receiveShadow position={[0, buildingHeight / 2, 0]}>
            <cylinderGeometry args={[1.35, 1.65, buildingHeight, 8]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={selected ? 2 : 0.7}
              transparent
              opacity={opacity}
              roughness={0.28}
              metalness={0.5}
            />
          </mesh>

          <mesh position={[0, buildingHeight + 0.18, 0]}>
            <cylinderGeometry args={[0.75, 1.1, 0.36, 8]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={1.5}
              transparent
              opacity={opacity}
              metalness={0.65}
              roughness={0.18}
            />
          </mesh>

          {/* Core */}
          <mesh position={[0, buildingHeight * 0.58, 1.46]}>
            <circleGeometry args={[0.34, 24]} />
            <meshBasicMaterial
              color="#ffffff"
              transparent
              opacity={dimmed ? 0.08 : 0.85}
            />
          </mesh>
        </group>
      )}

      {/* PLACE: landmark rather than normal building */}
      {kind === "PLACE" && (
        <group
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entity);
          }}
        >
          <mesh castShadow position={[0, buildingHeight / 2, 0]}>
            <cylinderGeometry args={[0.65, 1.15, buildingHeight, 12]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={selected ? 2.2 : 0.8}
              transparent
              opacity={opacity}
              metalness={0.3}
              roughness={0.42}
            />
          </mesh>

          <mesh position={[0, buildingHeight + 0.25, 0]}>
            <sphereGeometry args={[0.52, 20, 20]} />
            <meshStandardMaterial
              color={color}
              emissive={emissive}
              emissiveIntensity={1.8}
              transparent
              opacity={opacity}
            />
          </mesh>
        </group>
      )}

      {/* Unknown entity fallback */}
      {kind === "UNKNOWN" && (
        <mesh
          castShadow
          position={[0, buildingHeight / 2, 0]}
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entity);
          }}
        >
          <octahedronGeometry args={[1.1 * importance]} />
          <meshStandardMaterial
            color={color}
            emissive={emissive}
            emissiveIntensity={selected ? 1.8 : 0.65}
            transparent
            opacity={opacity}
            metalness={0.45}
            roughness={0.3}
          />
        </mesh>
      )}

      {/* Entity name */}
      {!dimmed && (
        <Html
          position={[0, buildingHeight + 1.55, 0]}
          center
          distanceFactor={10}
          zIndexRange={[20, 0]}
        >
          <div
            className={[
              "pointer-events-none min-w-max rounded-lg border px-3 py-2",
              "bg-black/80 text-center shadow-xl backdrop-blur-md",
              selected ? "border-cyan-200/70" : "border-white/10",
            ].join(" ")}
          >
            <div className="text-[11px] font-semibold text-white">
              {entity.name}
            </div>

            <div className="mt-1 text-[8px] uppercase tracking-[0.18em] text-white/45">
              {kind} · {entity.connection_count}{" "}
              {entity.connection_count === 1 ? "link" : "links"}
            </div>
          </div>
        </Html>
      )}

      {/* Local light only for important / selected entities */}
      {(selected || entity.connection_count >= 3) && !dimmed && (
        <pointLight
          position={[0, buildingHeight + 0.8, 0]}
          color={color}
          intensity={selected ? 5 : 2}
          distance={selected ? 8 : 5}
        />
      )}
    </group>
  );
}
