export const ENTITY_COLORS = {
  PERSON: "#facc15",
  PLACE: "#22c55e",
  ORGANIZATION: "#8b5cf6",
  PROJECT: "#ec4899",
  SYSTEM: "#06b6d4",
  UNKNOWN: "#60a5fa",
} as const;

export const ENTITY_EMISSIVE = {
  PERSON: "#ca8a04",
  PLACE: "#15803d",
  ORGANIZATION: "#6d28d9",
  PROJECT: "#be185d",
  SYSTEM: "#0891b2",
  UNKNOWN: "#2563eb",
} as const;

export const RELATIONSHIP_COLORS: Record<string, string> = {
  WORKS_WITH: "#22c55e",
  CREATED: "#3b82f6",
  CONNECTED_TO: "#06b6d4",
  VISITED: "#f97316",
  LIVES_IN: "#10b981",
  ADVISES: "#a855f7",
  LEADS: "#eab308",
  MAINTAINS: "#ef4444",
};