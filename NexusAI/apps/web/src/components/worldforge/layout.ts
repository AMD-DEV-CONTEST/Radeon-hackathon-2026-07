import type { WorldForgeData } from "@/lib/api";

import type { DistrictData, LayoutData, Vec3 } from "./types";
import { entityKind } from "./utils";

const DISTRICT_RADIUS = 16;
const DISTRICT_MEMBER_RADIUS = 5.2;
const HUB_RADIUS = 9.5;
const FALLBACK_RADIUS = 22;

const PLACE_RELATIONSHIPS = new Set([
  "LIVES_IN",
  "LOCATED_IN",
  "BASED_IN",
  "WORKS_AT",
  "WORKS_IN",
  "VISITED",
]);

const HUB_RELATIONSHIPS = new Set([
  "WORKS_WITH",
  "MAINTAINS",
  "ADVISES",
  "CREATED",
  "CONNECTED_TO",
  "CONTAINS",
  "LEADS",
]);

function deterministicAngle(id: string): number {
  let hash = 0;

  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }

  return ((hash % 360) * Math.PI) / 180;
}

function offsetPosition(
  origin: Vec3,
  id: string,
  radius: number,
): Vec3 {
  const angle = deterministicAngle(id);

  return [
    origin[0] + Math.cos(angle) * radius,
    0.12,
    origin[2] + Math.sin(angle) * radius,
  ];
}

export function buildKnowledgeLayout(
  data: WorldForgeData | null,
): LayoutData {
  const positions = new Map<string, Vec3>();
  const districtMap = new Map<string, DistrictData>();

  if (!data || data.entities.length === 0) {
    return {
      positions,
      districts: [],
    };
  }

  const byId = new Map(
    data.entities.map((entity) => [entity.id, entity]),
  );

  /*
   * ------------------------------------------------------------
   * 1. PLACE ENTITIES BECOME DISTRICTS
   * ------------------------------------------------------------
   */

  const places = data.entities.filter(
    (entity) => entityKind(entity.entity_type) === "PLACE",
  );

  places.forEach((place, index) => {
    const angle =
      places.length === 1
        ? 0
        : (index / places.length) * Math.PI * 2 - Math.PI / 4;

    const radius = places.length === 1 ? 0 : DISTRICT_RADIUS;

    const position: Vec3 = [
      Math.cos(angle) * radius,
      0.12,
      Math.sin(angle) * radius,
    ];

    positions.set(place.id, position);

    districtMap.set(place.id, {
      id: place.id,
      name: place.name,
      position,
      members: [],
    });
  });

  /*
   * ------------------------------------------------------------
   * 2. DISCOVER DISTRICT MEMBERS
   * ------------------------------------------------------------
   */

  for (const relationship of data.relationships) {
    const relation = relationship.relationship_type.toUpperCase();

    if (!PLACE_RELATIONSHIPS.has(relation)) continue;

    const source = byId.get(relationship.source_entity_id);
    const target = byId.get(relationship.target_entity_id);

    if (!source || !target) continue;

    const sourceIsPlace =
      entityKind(source.entity_type) === "PLACE";

    const targetIsPlace =
      entityKind(target.entity_type) === "PLACE";

    const place = sourceIsPlace
      ? source
      : targetIsPlace
        ? target
        : null;

    const member = sourceIsPlace
      ? target
      : targetIsPlace
        ? source
        : null;

    if (!place || !member) continue;

    const district = districtMap.get(place.id);

    if (
      district &&
      !district.members.includes(member.id)
    ) {
      district.members.push(member.id);
    }
  }

  /*
   * ------------------------------------------------------------
   * 3. POSITION DISTRICT MEMBERS
   * ------------------------------------------------------------
   */

  districtMap.forEach((district) => {
    const members = [...district.members].sort();

    members.forEach((memberId, index) => {
      if (positions.has(memberId)) return;

      const count = Math.max(members.length, 1);

      const angle =
        (index / count) * Math.PI * 2 +
        deterministicAngle(memberId) * 0.15;

      const radius =
        DISTRICT_MEMBER_RADIUS +
        (index % 2) * 1.4;

      positions.set(memberId, [
        district.position[0] + Math.cos(angle) * radius,
        0.12,
        district.position[2] + Math.sin(angle) * radius,
      ]);
    });
  });

  /*
   * ------------------------------------------------------------
   * 4. POSITION IMPORTANT HUBS
   *
   * Projects, organizations and systems that are not already
   * inside a district become central knowledge landmarks.
   * ------------------------------------------------------------
   */

  const hubs = data.entities
    .filter((entity) => {
      if (positions.has(entity.id)) return false;

      const kind = entityKind(entity.entity_type);

      return (
        kind === "PROJECT" ||
        kind === "ORGANIZATION" ||
        kind === "SYSTEM"
      );
    })
    .sort(
      (a, b) =>
        b.connection_count - a.connection_count ||
        a.name.localeCompare(b.name),
    );

  hubs.forEach((hub, index) => {
    const angle =
      (index / Math.max(hubs.length, 1)) * Math.PI * 2 +
      Math.PI / 6;

    const radius =
      hubs.length === 1
        ? 0
        : HUB_RADIUS + (index % 2) * 2;

    positions.set(hub.id, [
      Math.cos(angle) * radius,
      0.12,
      Math.sin(angle) * radius,
    ]);
  });

  /*
   * ------------------------------------------------------------
   * 5. PULL CONNECTED ENTITIES TOWARD HUBS
   * ------------------------------------------------------------
   */

  // Multiple passes allow chains such as:
  //
  // NexusAI -> MemoryWeaver -> another entity
  //
  // to progressively acquire useful positions.
  for (let pass = 0; pass < 3; pass += 1) {
    for (const relationship of data.relationships) {
      const relation =
        relationship.relationship_type.toUpperCase();

      if (!HUB_RELATIONSHIPS.has(relation)) continue;

      const sourceId = relationship.source_entity_id;
      const targetId = relationship.target_entity_id;

      const sourcePosition = positions.get(sourceId);
      const targetPosition = positions.get(targetId);

      if (sourcePosition && !targetPosition) {
        positions.set(
          targetId,
          offsetPosition(
            sourcePosition,
            targetId,
            3.8 + pass * 0.45,
          ),
        );
      }

      if (targetPosition && !sourcePosition) {
        positions.set(
          sourceId,
          offsetPosition(
            targetPosition,
            sourceId,
            3.8 + pass * 0.45,
          ),
        );
      }
    }
  }

  /*
   * ------------------------------------------------------------
   * 6. DISCONNECTED ENTITIES
   *
   * Truly disconnected knowledge goes around the outer edge.
   * This makes disconnected data visually obvious rather than
   * mixing it randomly into meaningful clusters.
   * ------------------------------------------------------------
   */

  const remaining = data.entities
    .filter((entity) => !positions.has(entity.id))
    .sort((a, b) => a.name.localeCompare(b.name));

  remaining.forEach((entity, index) => {
    const angle =
      (index / Math.max(remaining.length, 1)) *
        Math.PI *
        2 -
      Math.PI / 2;

    const radius =
      FALLBACK_RADIUS + (index % 2) * 2;

    positions.set(entity.id, [
      Math.cos(angle) * radius,
      0.12,
      Math.sin(angle) * radius,
    ]);
  });

  return {
    positions,
    districts: Array.from(districtMap.values()),
  };
}

export function getLayoutBounds(layout: LayoutData) {
  const values=Array.from(layout.positions.values());
  if(values.length===0) return {center:[0,0,0] as Vec3,radius:18};
  let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;
  for(const p of values){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minZ=Math.min(minZ,p[2]);maxZ=Math.max(maxZ,p[2]);}
  const cx=(minX+maxX)/2, cz=(minZ+maxZ)/2;
  const radius=Math.max(10,Math.max(maxX-minX,maxZ-minZ)*0.62+8);
  return {center:[cx,0,cz] as Vec3,radius};
}

export function getWorldViewCamera(layout: LayoutData) {
 const {center,radius}=getLayoutBounds(layout);
 const distance=Math.max(24,Math.min(68,radius*1.7));
 return {
   target:[center[0],0,center[2]] as Vec3,
   position:[center[0]+distance*0.72,distance*0.78,center[2]+distance*0.72] as Vec3,
   minDistance:Math.max(8,radius*0.35),
   maxDistance:Math.max(42,radius*2.4),
 };
}
