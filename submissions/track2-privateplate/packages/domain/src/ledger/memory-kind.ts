/**
 * Agent-facing memory kind vocabulary vs legacy DB storage.
 * Agent tools expose preference | health_fact; older rows may store taste.
 */
export type AgentMemoryKind = "preference" | "health_fact";

const AGENT_MEMORY_KINDS = new Set<AgentMemoryKind>([
  "preference",
  "health_fact"
]);

/** Normalize a stored preference row kind for agent / oracle consumers. */
export function normalizeAgentPreferenceKind(dbKind: string): AgentMemoryKind {
  if (dbKind === "preference" || dbKind === "taste") {
    return "preference";
  }
  return "preference";
}

/** Persist agent-declared memory kind; maps legacy synonyms to canonical storage. */
export function persistAgentMemoryKind(
  kind: AgentMemoryKind | string
): AgentMemoryKind {
  if (kind === "health_fact") return "health_fact";
  if (kind === "preference" || kind === "taste") return "preference";
  return AGENT_MEMORY_KINDS.has(kind as AgentMemoryKind)
    ? (kind as AgentMemoryKind)
    : "preference";
}
