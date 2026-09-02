export const ORCHESTRATION_QUERY_KEYS = {
  all: ["orchestration"] as const,
  snapshot: (candidateId: string) =>
    [...ORCHESTRATION_QUERY_KEYS.all, "snapshot", candidateId] as const,
  workflow: (candidateId: string) =>
    [...ORCHESTRATION_QUERY_KEYS.all, "workflow", candidateId] as const,
} as const;

export const ORCHESTRATION_MUTATION_KEYS = {
  start: ["orchestration", "start"] as const,
  retry: ["orchestration", "retry"] as const,
  cancel: ["orchestration", "cancel"] as const,
  finalize: ["orchestration", "finalize"] as const,
} as const;
