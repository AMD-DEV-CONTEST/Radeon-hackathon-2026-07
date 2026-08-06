"use client";

import type { WorldForgeEntity } from "@/lib/api";
import ProximityLabel from "./ProximityLabel";
import type { Vec3 } from "./types";

export default function CharacterNameplate({
  entity,
  position,
}: {
  entity: WorldForgeEntity;
  position: Vec3;
}) {
  return (
    <ProximityLabel
      position={[position[0], position[1] + 2.35, position[2]]}
      near={4.5}
      far={10}
      worldFar={16}
    >
      <div className="pointer-events-none whitespace-nowrap rounded-md border border-white/10 bg-black/70 px-2 py-1 text-[10px] text-white backdrop-blur-md">
        <div className="font-semibold">{entity.name}</div>
        <div className="mt-0.5 text-[8px] uppercase tracking-wider text-white/45">
          Person · {entity.connection_count} links
        </div>
      </div>
    </ProximityLabel>
  );
}
