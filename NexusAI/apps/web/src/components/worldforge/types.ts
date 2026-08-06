export type Vec3 = [number, number, number];

export type EntityKind =
  | "PERSON"
  | "PLACE"
  | "PROJECT"
  | "ORGANIZATION"
  | "SYSTEM"
  | "UNKNOWN";

export interface KnowledgeEntity {
  id: string;
  name: string;
  entity_type: string;
  description?: string | null;
  properties: Record<string, unknown>;
  connection_count: number;
}

export interface KnowledgeRelationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  properties: Record<string, unknown>;
}

export interface KnowledgeGraphData {
  world_id: string;
  entities: KnowledgeEntity[];
  relationships: KnowledgeRelationship[];
}

export interface DistrictData {
  id: string;
  name: string;
  position: Vec3;
  members: string[];
}

export interface LayoutData {
  positions: Map<string, Vec3>;
  districts: DistrictData[];
}

export interface InspectorState {
  entity: KnowledgeEntity | null;
}