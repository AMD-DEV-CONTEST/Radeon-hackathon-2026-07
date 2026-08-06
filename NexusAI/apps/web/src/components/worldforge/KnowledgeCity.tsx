"use client";
import { Html } from "@react-three/drei";
import { useMemo, useState } from "react";
import type { WorldForgeData, WorldForgeEntity } from "@/lib/api";
import EntityStructure from "./EntityStructure";
import KnowledgeDistrict from "./KnowledgeDistrict";
import RelationshipPath from "./RelationshipPath";
import { buildKnowledgeLayout } from "./layout";

import WorldTerrain from "./WorldTerrain";
import WorldLighting from "./WorldLighting";
import DistrictEnvironment from "./DistrictEnvironment";
import NexusPlaza from "./NexusPlaza";
import DistrictRoadNetwork from "./DistrictRoadNetwork";

export default function KnowledgeCity({
  data,
}: {
  data: WorldForgeData | null;
}) {
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const layout = useMemo(() => buildKnowledgeLayout(data), [data]);
  const connectedEntityIds = useMemo(() => {
    const ids = new Set<string>();
    if (!data || !selectedEntityId) return ids;
    ids.add(selectedEntityId);
    for (const r of data.relationships) {
      if (r.source_entity_id === selectedEntityId) ids.add(r.target_entity_id);
      if (r.target_entity_id === selectedEntityId) ids.add(r.source_entity_id);
    }
    return ids;
  }, [data, selectedEntityId]);
  const selectedEntity = useMemo(
    () =>
      !data || !selectedEntityId
        ? null
        : (data.entities.find((e) => e.id === selectedEntityId) ?? null),
    [data, selectedEntityId],
  );
  if (!data) return null;
  const handleSelect = (entity: WorldForgeEntity) =>
    setSelectedEntityId(entity.id);
  return (
    <>
      <group>
      <WorldLighting />
      <WorldTerrain layout={layout} />
      <DistrictRoadNetwork districts={layout.districts} />
      <NexusPlaza />
        {layout.districts.map((d) => (
          <KnowledgeDistrict key={d.id} district={d} />
        ))}
        {layout.districts.map((district) => (
        <DistrictEnvironment key={`environment-${district.id}`} district={district} />
      ))}
      {data.relationships.map((r) => {
          const source = layout.positions.get(r.source_entity_id),
            target = layout.positions.get(r.target_entity_id);
          if (!source || !target) return null;
          const highlighted =
            selectedEntityId !== null &&
            (r.source_entity_id === selectedEntityId ||
              r.target_entity_id === selectedEntityId);
          return (
            <RelationshipPath
              key={r.id}
              relationship={r}
              source={source}
              target={target}
              highlighted={highlighted}
              dimmed={selectedEntityId !== null && !highlighted}
            />
          );
        })}
        {data.entities.map((entity) => {
          const position = layout.positions.get(entity.id);
          if (!position) return null;
          return (
            <EntityStructure
              key={entity.id}
              entity={entity}
              position={position}
              selected={entity.id === selectedEntityId}
              dimmed={
                selectedEntityId !== null && !connectedEntityIds.has(entity.id)
              }
              onSelect={handleSelect}
            />
          );
        })}
      </group>
    </>
  );
}
