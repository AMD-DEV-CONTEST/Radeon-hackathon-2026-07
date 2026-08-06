import type { EnvironmentRenderSpec } from "./environmentTypes";
import type { KnowledgeGraphData } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function buildWorldContext(data: KnowledgeGraphData): string {
  return data.entities
    .flatMap((entity) => [
      entity.name,
      entity.entity_type,
      entity.description ?? "",
      JSON.stringify(entity.properties ?? {}),
    ])
    .filter(Boolean)
    .join(" ");
}

export async function getEnvironmentRenderSpec(
  worldId: string,
  data: KnowledgeGraphData,
): Promise<EnvironmentRenderSpec> {
  const response = await fetch(`${API_URL}/api/worlds/${worldId}/render-spec`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: buildWorldContext(data) }),
  });

  if (!response.ok) {
    throw new Error(`Environment render spec failed: ${response.status}`);
  }

  return response.json() as Promise<EnvironmentRenderSpec>;
}
