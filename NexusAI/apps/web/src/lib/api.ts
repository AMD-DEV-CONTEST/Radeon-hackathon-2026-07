export type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

export type World = {
  id: string;
  name: string;
  description: string;
  route: string;
  status: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/api/health`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error("Nexus API is unavailable");
  }

  return response.json();
}

export async function getWorlds(): Promise<World[]> {
  const response = await fetch(`${API_URL}/api/worlds`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error("Unable to load Nexus Worlds");
  }

  return response.json();
}


export type WorldForgeEntity = {
  id: string;
  name: string;
  entity_type: string;
  description?: string | null;
  properties: Record<string, unknown>;
  connection_count: number;
};

export type WorldForgeRelationship = {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  properties: Record<string, unknown>;
};

export type WorldForgeData = {
  world_id: string;
  entities: WorldForgeEntity[];
  relationships: WorldForgeRelationship[];
};

export async function getWorldForgeData(
  worldId: string
): Promise<WorldForgeData> {
  const response = await fetch(`${API_URL}/api/worlds/${worldId}/worldforge`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Unable to load WorldForge knowledge");
  }

  return response.json();
}
