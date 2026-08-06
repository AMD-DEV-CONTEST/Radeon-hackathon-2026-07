"use client";

import type { WorldForgeEntity } from "@/lib/api";
import type { Vec3 } from "./types";
import { entityKind } from "./utils";
import OrganizationBuilding from "./OrganizationBuilding";
import PersonEntity from "./PersonEntity";
import PlaceLandmark from "./PlaceLandmark";
import ProjectBuilding from "./ProjectBuilding";
import SystemStructure from "./SystemStructure";
import UnknownStructure from "./UnknownStructure";
import ProximityLabel from "./ProximityLabel";
import SemanticAsset from "./SemanticAsset";

export default function EntityStructure({
  entity,
  position,
  selected,
  dimmed,
  onSelect,
}: {
  entity: WorldForgeEntity;
  position: Vec3;
  selected: boolean;
  dimmed: boolean;
  onSelect: (e: WorldForgeEntity) => void;
}) {
  const kind = entityKind(entity.entity_type);
  return (
    <group
      position={position}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(entity);
      }}
    >
      <SemanticAsset
        kind={kind}
        fallback={
          <>
            {kind === "PERSON" && (
              <PersonEntity
                entity={entity}
                selected={selected}
                dimmed={dimmed}
              />
            )}
            {kind === "PLACE" && (
              <PlaceLandmark selected={selected} dimmed={dimmed} />
            )}
            {kind === "ORGANIZATION" && (
              <OrganizationBuilding selected={selected} dimmed={dimmed} />
            )}
            {kind === "PROJECT" && (
              <ProjectBuilding selected={selected} dimmed={dimmed} />
            )}
            {kind === "SYSTEM" && (
              <SystemStructure selected={selected} dimmed={dimmed} />
            )}
            {kind === "UNKNOWN" && (
              <UnknownStructure selected={selected} dimmed={dimmed} />
            )}
          </>
        }
      />
      <ProximityLabel
        position={[0, kind === "PERSON" ? 2.65 : 4.15, 0]}
        near={7}
        far={kind === "PERSON" ? 18 : kind === "PLACE" ? 24 : 16}
        worldFar={32}
        major={kind === "PLACE" || kind === "ORGANIZATION"}
      >
        {" "}
        <div
          className={`pointer-events-none min-w-max rounded-lg border px-2.5 py-1.5 backdrop-blur-md ${selected ? "border-cyan-200/60 bg-cyan-950/80 text-cyan-50" : "border-white/10 bg-black/70 text-white/85"} ${dimmed ? "opacity-25" : "opacity-100"}`}
        >
          <div className="text-[9px] font-semibold tracking-wide">
            {entity.name}
          </div>
          <div className="mt-0.5 text-[7px] uppercase tracking-[0.2em] text-white/45">
            {kind} · {entity.connection_count} LINKS
          </div>
        </div>
      </ProximityLabel>
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.035, 0]}>
          <ringGeometry args={[1.7, 1.82, 64]} />
          <meshBasicMaterial color="#67e8f9" transparent opacity={0.9} />
        </mesh>
      )}
    </group>
  );
}
